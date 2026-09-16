"""Concrete ProvisioningAdapter (service.py's Protocol) against a real iDempiere
instance, per ADR-ERP-019's responsibility split: the Control Plane already owns the
canonical tenant_id/legal_entity_id/engine_instance_id/isolation_profile_id/
capability_binding_id identifiers by the time a request reaches this adapter (they are
plain fields on ErpProvisioningRequest); this adapter's job is the native half --
create/configure the AD_Client (and its accounting, localisation and warehouses) that
represents this legal entity inside a shared iDempiere EngineInstance, then record the
resulting (tenant_id, legal_entity_id) -> (AD_Client_ID, AD_Org_ID) mapping so
modules/context can resolve it afterwards (ADR-ERP-002).

Because ADR-ERP-021 chose Pattern B (a separate AD_Client per ZuriBeans market, not one
shared AD_Client with market AD_Orgs), each AD_Client here needs only its own default
organization -- AD_Org_ID 0, iDempiere's built-in "*" / All-Organizations id. Pattern
A's need for market-specific AD_Orgs under one shared AD_Client (which is what
StepKind.CREATE_ORGANISATION would be for) does not apply to this topology, and
planner.py never emits that step kind; apply()/check() raise a clear
ProvisioningStepError if they ever see one rather than silently no-op-ing.

Field names below (AD_Client.Value/Name, C_AcctSchema.Name/C_Currency_ID, etc.) are
drawn from iDempiere's standard, public AD_* schema -- they are NOT independently
verified against the REST API's request/response envelope for these specific endpoints
the way idempiere_client.py's own core shapes (auth, /models/{table}, /processes/{id})
were (that verification needs a live instance to do honestly, and none is reachable in
this environment -- see idempiere/rest-api/README.md and architecture/conformance.yaml).
This module is therefore code-complete against RestIdempiereClient's already-verified
transport shape, not independently proven correct end-to-end; verified here via
tests/unit/test_provisioning_idempiere_adapter.py against a fake IdempiereClient,
matching test_provisioning_service.py's own mocking style, not a live run.
"""

import re
from typing import Any, Protocol

from integration.idempiere_client import IdempiereClient, IdempiereClientError
from provisioning.model import ErpProvisioningRequest, ProvisioningStep, ReadinessCheck, StepKind

_ALL_ORGANIZATIONS_AD_ORG_ID = 0


class ProvisioningStepError(Exception):
    """A step kind this adapter cannot apply/check, or the underlying iDempiere call failed."""


class TenantMappingWriter(Protocol):
    def create_mapping(self, tenant_id: str, entity_id: str, ad_client_id: int, ad_org_id: int) -> None: ...
    def find_active_mapping(self, tenant_id: str, entity_id: str) -> tuple[int, int] | None: ...


class IdempiereProvisioningAdapter:
    """One instance is used for the whole of a single ErpProvisioningService.apply()
    call (see service.py: it loops over every pending step for one provisioning_id in
    one call). This adapter caches the AD_Client_ID that CREATE_CLIENT produces,
    in-memory, keyed by provisioning_id, so later steps in the *same* apply() call
    (CONFIGURE_ACCOUNTING, CONFIGURE_LOCALISATION, CREATE_WAREHOUSE, PERSIST_MAPPING)
    can use it without re-deriving it. That cache is process-local and not durable: if
    apply() is retried from a fresh process after CREATE_CLIENT already completed (per
    ProvisioningStore.completed_steps), this adapter falls back to
    TenantMappingWriter.find_active_mapping -- which only has an answer once
    PERSIST_MAPPING itself has already run once. A restart between CREATE_CLIENT
    succeeding and PERSIST_MAPPING running is therefore a genuine gap: this adapter
    cannot invent an AD_Client lookup-by-natural-key call the REST API spec doesn't
    document. Flagged here rather than papered over.
    """

    def __init__(self, client: IdempiereClient, mappings: TenantMappingWriter) -> None:
        self._client = client
        self._mappings = mappings
        self._ad_client_id_cache: dict[str, int] = {}
        # Results already applied in *this* process, keyed by step.key -- the only
        # thing check() has to go on beyond re-querying iDempiere/the mapping store,
        # since ProvisioningStep itself carries only the desired payload, not the
        # result of applying it (that lives in ProvisioningStore, which this adapter
        # has no handle on). Matches how test_provisioning_service.py exercises one
        # adapter instance across both apply() and readiness() in the same process.
        self._step_results: dict[str, dict] = {}

    def apply(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        try:
            if step.kind is StepKind.CREATE_CLIENT:
                result = self._apply_create_client(request, step)
            elif step.kind is StepKind.CONFIGURE_ACCOUNTING:
                result = self._apply_configure_accounting(request, step)
            elif step.kind is StepKind.CONFIGURE_LOCALISATION:
                result = self._apply_configure_localisation(request, step)
            elif step.kind is StepKind.CREATE_WAREHOUSE:
                result = self._apply_create_warehouse(request, step)
            elif step.kind is StepKind.PERSIST_MAPPING:
                result = self._apply_persist_mapping(request, step)
            else:
                raise ProvisioningStepError(f"No handler for step kind {step.kind.value!r} ({step.key})")
        except IdempiereClientError as exc:
            raise ProvisioningStepError(f"{step.kind.value} ({step.key}) failed: {exc}") from exc
        self._step_results[step.key] = result
        return result

    def check(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> ReadinessCheck:
        try:
            if step.kind is StepKind.CREATE_CLIENT:
                return self._check_record(step, "AD_Client")
            if step.kind is StepKind.CONFIGURE_ACCOUNTING:
                return self._check_record(step, "C_AcctSchema")
            if step.kind is StepKind.CONFIGURE_LOCALISATION:
                return self._check_client_field(request, step, "AD_Language")
            if step.kind is StepKind.CREATE_WAREHOUSE:
                return self._check_record(step, "M_Warehouse")
            if step.kind is StepKind.PERSIST_MAPPING:
                return self._check_persist_mapping(request, step)
        except IdempiereClientError as exc:
            return ReadinessCheck(f"step.{step.key}", False, f"could not verify: {exc}")
        raise ProvisioningStepError(f"No handler for step kind {step.kind.value!r} ({step.key})")

    # -- CREATE_CLIENT --------------------------------------------------------------

    def _apply_create_client(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        fields: dict[str, Any] = {
            "Value": _slug(step.payload["Name"]),
            "Name": step.payload["Name"],
            "IsActive": "Y",
        }
        ad_client_id = self._client.create_record("AD_Client", fields)
        self._ad_client_id_cache[request.provisioning_id] = ad_client_id
        return {"AD_Client_ID": ad_client_id, "AD_Org_ID": _ALL_ORGANIZATIONS_AD_ORG_ID}

    # -- CONFIGURE_ACCOUNTING ---------------------------------------------------------

    def _apply_configure_accounting(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        ad_client_id = self._require_ad_client_id(request)
        fields: dict[str, Any] = {
            "AD_Client_ID": ad_client_id,
            "Name": f"{request.legal_name} Accounting Schema",
            "C_Currency_ID": step.payload["functional_currency"],
            "CostingMethod": step.payload["costing_method"],
            "IsActive": "Y",
        }
        acct_schema_id = self._client.create_record("C_AcctSchema", fields)
        return {"C_AcctSchema_ID": acct_schema_id}

    # -- CONFIGURE_LOCALISATION -------------------------------------------------------

    def _apply_configure_localisation(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        ad_client_id = self._require_ad_client_id(request)
        fields: dict[str, Any] = {
            "AD_Language": _language_for_country(step.payload["country_code"]),
            "Info": step.payload["profile"],
        }
        self._client.update_record("AD_Client", ad_client_id, fields)
        return {"AD_Client_ID": ad_client_id, **fields}

    # -- CREATE_WAREHOUSE --------------------------------------------------------------

    def _apply_create_warehouse(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        ad_client_id = self._require_ad_client_id(request)
        fields: dict[str, Any] = {
            "AD_Client_ID": ad_client_id,
            "AD_Org_ID": _ALL_ORGANIZATIONS_AD_ORG_ID,
            "Value": step.payload["warehouse_code"],
            "Name": step.payload["warehouse_code"],
            "IsActive": "Y",
        }
        warehouse_id = self._client.create_record("M_Warehouse", fields)
        return {"M_Warehouse_ID": warehouse_id}

    # -- PERSIST_MAPPING ----------------------------------------------------------------

    def _apply_persist_mapping(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        ad_client_id = self._require_ad_client_id(request)
        self._mappings.create_mapping(
            tenant_id=step.payload["tenant_id"],
            entity_id=step.payload["legal_entity_id"],
            ad_client_id=ad_client_id,
            ad_org_id=_ALL_ORGANIZATIONS_AD_ORG_ID,
        )
        return {"AD_Client_ID": ad_client_id, "AD_Org_ID": _ALL_ORGANIZATIONS_AD_ORG_ID}

    # -- shared helpers -------------------------------------------------------------------

    def _require_ad_client_id(self, request: ErpProvisioningRequest) -> int:
        cached = self._ad_client_id_cache.get(request.provisioning_id)
        if cached is not None:
            return cached
        mapping = self._mappings.find_active_mapping(request.tenant_id, request.legal_entity_id)
        if mapping is None:
            raise ProvisioningStepError(
                "No AD_Client_ID available for this provisioning operation -- CREATE_CLIENT "
                "must run (in this process) or PERSIST_MAPPING must already have completed "
                "before this step can proceed"
            )
        ad_client_id, _ad_org_id = mapping
        self._ad_client_id_cache[request.provisioning_id] = ad_client_id
        return ad_client_id

    def _check_record(self, step: ProvisioningStep, table: str) -> ReadinessCheck:
        result = self._step_results.get(step.key)
        record_id = result.get(f"{table}_ID") if result else None
        if record_id is None:
            return ReadinessCheck(f"step.{step.key}", False, f"{table} not yet applied in this process")
        record = self._client.get_record(table, record_id)
        active = record.get("IsActive") in ("Y", True)
        return ReadinessCheck(f"step.{step.key}", active, f"{table}#{record_id} IsActive={record.get('IsActive')!r}")

    def _check_client_field(self, request: ErpProvisioningRequest, step: ProvisioningStep, field: str) -> ReadinessCheck:
        ad_client_id = self._ad_client_id_cache.get(request.provisioning_id)
        if ad_client_id is None:
            mapping = self._mappings.find_active_mapping(request.tenant_id, request.legal_entity_id)
            ad_client_id = mapping[0] if mapping else None
        if ad_client_id is None:
            return ReadinessCheck(f"step.{step.key}", False, "AD_Client not yet created")
        record = self._client.get_record("AD_Client", ad_client_id)
        configured = bool(record.get(field))
        return ReadinessCheck(f"step.{step.key}", configured, f"AD_Client#{ad_client_id}.{field}={record.get(field)!r}")

    def _check_persist_mapping(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> ReadinessCheck:
        mapping = self._mappings.find_active_mapping(step.payload["tenant_id"], step.payload["legal_entity_id"])
        ready = mapping is not None
        detail = f"ad_client_id={mapping[0]}, ad_org_id={mapping[1]}" if mapping else "no active tenant mapping"
        return ReadinessCheck(f"step.{step.key}", ready, detail)


def _slug(name: str) -> str:
    """A short, iDempiere-Value-shaped (uppercase, underscore-separated) natural key
    derived from a human-readable name. AD_Client.Value has a real length limit in
    iDempiere (40 chars); truncate defensively since this is never verified live."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return slug[:40]


_LANGUAGE_BY_COUNTRY = {
    "UG": "en_US",
    "ZA": "en_US",
}


def _language_for_country(country_code: str) -> str:
    return _LANGUAGE_BY_COUNTRY.get(country_code, "en_US")
