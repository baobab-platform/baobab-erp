"""Concrete ProvisioningAdapter (service.py's Protocol) against a real iDempiere
instance. Mapping-driven, never idempotent-by-Name: retries resolve an already-created
native record through ProvisioningMappingStore (provisioning_id + resource_key ->
native iDempiere ID), never by searching iDempiere for a record with a matching Name --
that would risk creating a duplicate AD_Client/AD_Org/M_Warehouse after a partial
failure, or silently reusing an unrelated record that happens to share a name.

PERSIST_MAPPING additionally writes the tenant/legal-entity -> AD_Client/AD_Org mapping
that modules/context actually resolves against (baobab.tenant_mapping, ADR-ERP-002),
via the optional `tenant_mappings` collaborator -- without it, provisioning would mark
itself complete without ever making the new legal entity resolvable, which defeats the
point of provisioning. `tenant_mappings` is optional (defaults to None) so callers that
only care about native iDempiere state (e.g. existing unit tests) don't need to supply
one; server.py's real wiring always will.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from provisioning.model import ErpProvisioningRequest, ProvisioningStep, ReadinessCheck, StepKind

_ALL_ORGANIZATIONS_AD_ORG_ID = 0


class ProvisioningMappingStore(Protocol):
    def get_native_id(self, *, provisioning_id: str, resource_key: str) -> int | None: ...
    def put_native_id(self, *, provisioning_id: str, resource_key: str, native_id: int) -> None: ...


class ProvisioningIdempiereClient(Protocol):
    def get_record(self, table: str, record_id: int) -> dict[str, Any]: ...
    def create_record(self, table: str, fields: dict[str, Any]) -> int: ...
    def update_record(self, table: str, record_id: int, fields: dict[str, Any]) -> None: ...
    def execute_process(self, process_id: int, parameters: dict[str, Any]) -> dict[str, Any]: ...


class TenantMappingWriter(Protocol):
    """The write path onto baobab.tenant_mapping (modules/context/postgres_store.py's
    PostgresTenantMappingStore) that PERSIST_MAPPING needs to make context resolution
    actually work for the legal entity this operation just provisioned."""

    def create_mapping(self, tenant_id: str, entity_id: str, ad_client_id: int, ad_org_id: int) -> None: ...


@dataclass(slots=True)
class IdempiereProvisioningAdapter:
    """Concrete adapter for the existing ErpProvisioningService.

    It is deliberately mapping-driven: retries never guess native records by Name.
    The canonical provisioning operation owns durable native IDs, preventing duplicate
    AD_Client/AD_Org/M_Warehouse creation after a partial failure.
    """

    client: ProvisioningIdempiereClient
    mappings: ProvisioningMappingStore
    tenant_mappings: TenantMappingWriter | None = None

    def apply(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict:
        handlers = {
            StepKind.CREATE_CLIENT: self._create_client,
            StepKind.CREATE_ORGANISATION: self._create_org,
            StepKind.CONFIGURE_ACCOUNTING: self._configure_accounting,
            StepKind.CONFIGURE_LOCALISATION: self._configure_localisation,
            StepKind.CREATE_WAREHOUSE: self._create_warehouse,
            StepKind.PERSIST_MAPPING: self._persist_mapping,
        }
        return handlers[step.kind](request, step)

    def check(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> ReadinessCheck:
        resource_key = self._resource_key(step)
        if step.kind in {StepKind.CONFIGURE_ACCOUNTING, StepKind.CONFIGURE_LOCALISATION, StepKind.PERSIST_MAPPING}:
            marker = self.mappings.get_native_id(provisioning_id=request.provisioning_id, resource_key=resource_key)
            return ReadinessCheck(f"idempiere.{step.kind.value}", marker is not None, "applied" if marker is not None else "not applied")
        native_id = self.mappings.get_native_id(provisioning_id=request.provisioning_id, resource_key=resource_key)
        if native_id is None:
            return ReadinessCheck(f"idempiere.{step.kind.value}", False, "native mapping missing")
        table = self._table(step.kind)
        try:
            record = self.client.get_record(table, native_id)
        except Exception as exc:
            return ReadinessCheck(f"idempiere.{step.kind.value}", False, f"native record unavailable: {exc}")
        active = bool(record.get("IsActive", True))
        return ReadinessCheck(f"idempiere.{step.kind.value}", active, f"{table}:{native_id}")

    def _create_client(self, request, step):
        result = self._create_once(
            request, step, "AD_Client",
            {"Name": request.legal_name, "Value": self._safe_value(request.legal_entity_id), "IsActive": True},
        )
        # Stashed under a request-scoped key (not step.key, which is digest-specific and
        # not derivable from inside _persist_mapping) so PERSIST_MAPPING can find "the"
        # AD_Client_ID this operation created regardless of which step produced it.
        self.mappings.put_native_id(
            provisioning_id=request.provisioning_id, resource_key=self._client_alias_key(), native_id=result["id"]
        )
        return result

    def _create_org(self, request, step):
        fields = dict(step.payload)
        fields.setdefault("Name", request.legal_name)
        fields.setdefault("Value", self._safe_value(request.legal_entity_id))
        fields.setdefault("IsActive", True)
        return self._create_once(request, step, "AD_Org", fields)

    def _create_warehouse(self, request, step):
        code = step.payload["warehouse_code"]
        fields = {"Name": code, "Value": code, "IsActive": True}
        return self._create_once(request, step, "M_Warehouse", fields)

    def _configure_accounting(self, request, step):
        # Native accounting schema/tax/COA creation is deployment-specific and must
        # be performed through an approved iDempiere process/plugin. We fail closed
        # unless process IDs are supplied in the deterministic plan payload.
        process_id = step.payload.get("process_id")
        if process_id is None:
            raise ValueError("CONFIGURE_ACCOUNTING requires approved iDempiere process_id")
        result = self.client.execute_process(int(process_id), dict(step.payload))
        self._mark_applied(request, step)
        return {"process_id": int(process_id), "result": result}

    def _configure_localisation(self, request, step):
        process_id = step.payload.get("process_id")
        if process_id is None:
            raise ValueError("CONFIGURE_LOCALISATION requires certified localisation process_id")
        result = self.client.execute_process(int(process_id), dict(step.payload))
        self._mark_applied(request, step)
        return {"process_id": int(process_id), "result": result}

    def _persist_mapping(self, request, step):
        # The durable Baobab canonical mapping is owned outside iDempiere. This marker
        # means the ERP-side provisioning step completed; CP/shared mapping publication
        # remains an explicit integration concern rather than being silently invented.
        self._mark_applied(request, step)
        result = {"canonical": dict(step.payload), "persisted": True}
        if self.tenant_mappings is not None:
            ad_client_id = self.mappings.get_native_id(
                provisioning_id=request.provisioning_id, resource_key=self._client_alias_key()
            )
            if ad_client_id is None:
                raise ValueError(
                    "PERSIST_MAPPING requires AD_Client_ID from a completed CREATE_CLIENT step "
                    "(in this process or a prior one) before context resolution can be wired up"
                )
            self.tenant_mappings.create_mapping(
                tenant_id=step.payload["tenant_id"],
                entity_id=step.payload["legal_entity_id"],
                ad_client_id=ad_client_id,
                ad_org_id=_ALL_ORGANIZATIONS_AD_ORG_ID,
            )
            result["tenant_mapping"] = {"ad_client_id": ad_client_id, "ad_org_id": _ALL_ORGANIZATIONS_AD_ORG_ID}
        return result

    def _create_once(self, request, step, table, fields):
        key = self._resource_key(step)
        existing = self.mappings.get_native_id(provisioning_id=request.provisioning_id, resource_key=key)
        if existing is not None:
            self.client.get_record(table, existing)
            return {"table": table, "id": existing, "reused": True}
        native_id = self.client.create_record(table, fields)
        self.mappings.put_native_id(provisioning_id=request.provisioning_id, resource_key=key, native_id=native_id)
        return {"table": table, "id": native_id, "reused": False}

    def _mark_applied(self, request, step):
        # 1 is a non-native sentinel only for process/marker steps. Resource mappings
        # always contain the actual iDempiere record ID.
        self.mappings.put_native_id(provisioning_id=request.provisioning_id, resource_key=self._resource_key(step), native_id=1)

    @staticmethod
    def _resource_key(step): return f"{step.kind.value}:{step.key}"
    @staticmethod
    def _client_alias_key(): return "AD_Client:primary"
    @staticmethod
    def _safe_value(value): return value.replace("_", "-")[:40]
    @staticmethod
    def _table(kind):
        return {
            StepKind.CREATE_CLIENT: "AD_Client",
            StepKind.CREATE_ORGANISATION: "AD_Org",
            StepKind.CREATE_WAREHOUSE: "M_Warehouse",
        }[kind]
