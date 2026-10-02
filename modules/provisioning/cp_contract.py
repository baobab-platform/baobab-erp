"""The Control Plane ERP assignment (Shared control-plane/v1 ``ErpAssignment``) and what ERP adds to it.

Control Plane projects only facts it is the authority for: the legal entity's verified profile, the markets the
tenant participates in, and the resolved topology (engine, engine instance, the capability keys bound to it) under the
isolation requirement the approved plan was made under. Everything else a provisioning request needs is ERP's own and
comes from ERP-owned inputs, never from the caller's request or from guesses:

* native ``AD_Client`` placement   -> provisioning.legal_entity_policy (ADR-ERP-002 SS114, ADR-ERP-021)
* accounting configuration         -> a Finance-approved baseline (ADR-ERP-008), ``FinanceBaseline``
* per-market currencies, localisation profile and warehouses -> ``ErpMarketConfiguration``
* idempotency key                  -> derived here from the provisioning, legal entity and approved plan digest

Request is not authority: the assignment must name the tenant, provisioning and legal entity that were asked for.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Protocol

from provisioning.model import AccountingConfiguration, ErpProvisioningRequest, MarketConfiguration


class AssignmentError(ValueError):
    pass


# Shared erp-assignment.schema.json is closed (additionalProperties: false). Control Plane's registry identifiers and
# ERP-owned decisions are rejected by name so the failure says why, not just "unexpected member".
_ASSIGNMENT_MEMBERS = frozenset({
    "tenant_id", "tenant_provisioning_id", "plan_id", "plan_version", "plan_digest", "legal_entity", "markets", "engine_id", "engine_instance_id",
    "isolation_requirement", "capabilities", "issued_at", "expires_at",
})
_LEGAL_ENTITY_MEMBERS = frozenset({
    "legal_entity_id", "legal_name", "jurisdiction_code", "registration_identifiers", "verification_state",
})
_NOT_CONTROL_PLANE_MEMBERS = frozenset({
    "native_client_mode", "native_client_key", "capability_binding_id", "capability_bindings", "isolation_profile_id",
    "legal_entity_code", "target_environment", "currencies", "localisation_profile", "warehouse_codes",
})
ERP_ENGINE_ID = "baobab-erp"
_COMPANY_REGISTRATION = "COMPANY_REGISTRATION"


@dataclass(frozen=True, slots=True)
class CpMarketAssignment:
    market: str
    activities: frozenset[str]


@dataclass(frozen=True, slots=True)
class CpErpAssignment:
    """Authoritative CP projection consumed by baobab-erp (Shared ``ErpAssignment``)."""
    tenant_id: str
    tenant_provisioning_id: str
    plan_id: str
    plan_version: int
    plan_digest: str
    legal_entity_id: str
    legal_name: str
    jurisdiction_code: str
    registration_identifiers: tuple[Mapping[str, Any], ...]
    verification_state: str
    markets: tuple[CpMarketAssignment, ...]
    engine_id: str
    engine_instance_id: str
    isolation_requirement: str
    capabilities: frozenset[str]
    issued_at: datetime
    expires_at: datetime

    def validate(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        required = {
            "tenant_id": self.tenant_id, "tenant_provisioning_id": self.tenant_provisioning_id,
            "plan_id": self.plan_id, "plan_digest": self.plan_digest, "legal_entity_id": self.legal_entity_id,
            "legal_name": self.legal_name,
            "jurisdiction_code": self.jurisdiction_code, "engine_instance_id": self.engine_instance_id,
            "isolation_requirement": self.isolation_requirement,
        }
        missing = [k for k, v in required.items() if not str(v).strip()]
        if missing:
            raise AssignmentError(f"missing authoritative assignment fields: {', '.join(missing)}")
        if isinstance(self.plan_version, bool) or not isinstance(self.plan_version, int) or self.plan_version < 1:
            raise AssignmentError("plan_version must be an integer >= 1")
        if self.engine_id != ERP_ENGINE_ID:
            raise AssignmentError(f"the assignment is for engine {self.engine_id!r}, not {ERP_ENGINE_ID!r}")
        if self.verification_state != "VERIFIED":
            raise AssignmentError("the legal entity is not VERIFIED")
        if now >= self.expires_at:
            raise AssignmentError("authoritative CP assignment has expired")
        if not self.markets:
            raise AssignmentError("at least one CP-authorised market assignment is required")
        codes = [m.market for m in self.markets]
        if len(codes) != len(set(codes)):
            raise AssignmentError("duplicate market in CP assignment")
        if not self.capabilities:
            raise AssignmentError("the assignment binds no capability")

    def registration_identifier(self) -> str:
        """The one company registration number. None, or several, is ambiguity ERP will not resolve by guessing."""
        found = [i for i in self.registration_identifiers if i.get("type") == _COMPANY_REGISTRATION]
        if len(found) != 1 or not str(found[0].get("value", "")).strip():
            raise AssignmentError(f"the legal entity needs exactly one {_COMPANY_REGISTRATION} identifier, found {len(found)}")
        return str(found[0]["value"])

    def provisioning_record_id(self) -> str:
        """ERP's provisioning record for ONE legal entity under ONE approved plan version. The Control Plane provisioning id
        alone would collide across a tenant's legal entities, and a replan is a new version, not a rewrite of the old."""
        return f"{self.tenant_provisioning_id}.{self.legal_entity_id}.v{self.plan_version}"

    def idempotency_key(self) -> str:
        """ERP-owned: stable for one provisioning of one legal entity under one approved plan, new for a re-approved plan."""
        digest = hashlib.sha256(
            f"{self.tenant_provisioning_id}|{self.legal_entity_id}|{self.plan_id}|{self.plan_version}|{self.plan_digest}"
            .encode()).hexdigest()
        return f"erp-prov-{digest}"


class ControlPlaneAssignmentSource(Protocol):
    def resolve_erp_assignment(
        self, *, tenant_id: str, tenant_provisioning_id: str, legal_entity_id: str
    ) -> CpErpAssignment: ...


@dataclass(frozen=True, slots=True)
class FinanceBaseline:
    functional_currency: str
    fiscal_year_start_month: int
    chart_of_accounts_template: str
    accounting_schema: str
    tax_profile: str
    costing_method: str
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class ErpMarketConfiguration:
    """ERP-owned configuration of one market (ADR-ERP-009 localisation, ADR-ERP-015 warehouses). Control Plane does not
    store these, so a market without this configuration cannot be provisioned."""
    currencies: tuple[str, ...]
    localisation_profile: str
    warehouse_codes: tuple[str, ...] = ()


def materialize_request(
    assignment: CpErpAssignment,
    accounting: FinanceBaseline,
    market_configuration: Mapping[str, ErpMarketConfiguration],
    *,
    target_environment: str,
    effective_date: date,
    now: datetime | None = None,
) -> ErpProvisioningRequest:
    assignment.validate(now)
    markets = []
    for market in sorted(assignment.markets, key=lambda m: m.market):
        configured = market_configuration.get(market.market)
        if configured is None:
            raise AssignmentError(f"no ERP market configuration for {market.market!r}")
        markets.append(MarketConfiguration(
            market_id=market.market, country_code=market.market,
            participation_capabilities=frozenset(a.lower() for a in market.activities),
            currencies=configured.currencies, localisation_profile=configured.localisation_profile,
            warehouse_codes=configured.warehouse_codes))
    return ErpProvisioningRequest(
        provisioning_id=assignment.provisioning_record_id(),
        idempotency_key=assignment.idempotency_key(),
        tenant_id=assignment.tenant_id,
        legal_entity_id=assignment.legal_entity_id,
        legal_name=assignment.legal_name,
        registration_identifier=assignment.registration_identifier(),
        jurisdiction_code=assignment.jurisdiction_code,
        engine_instance_id=assignment.engine_instance_id,
        isolation_requirement=assignment.isolation_requirement,
        plan_digest=assignment.plan_digest,
        target_environment=target_environment,
        effective_date=effective_date,
        accounting=AccountingConfiguration(
            functional_currency=accounting.functional_currency,
            fiscal_year_start_month=accounting.fiscal_year_start_month,
            chart_of_accounts_template=accounting.chart_of_accounts_template,
            accounting_schema=accounting.accounting_schema,
            tax_profile=accounting.tax_profile,
            costing_method=accounting.costing_method,
            approved_by=accounting.approved_by,
            approved_at=accounting.approved_at,
        ),
        markets=tuple(markets),
        requested_capabilities=assignment.capabilities,
    )


def _closed(payload: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    if not isinstance(payload, Mapping):
        raise AssignmentError(f"{where} must be an object")
    named = sorted(set(payload) & _NOT_CONTROL_PLANE_MEMBERS)
    if named:
        raise AssignmentError(
            f"{where} carries {', '.join(named)}: not a Control Plane projection member (registry identifiers stay "
            "internal; native placement, accounting and per-market configuration are ERP-owned)")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise AssignmentError(f"{where} carries unknown members: {', '.join(unknown)}")
    absent = sorted(allowed - set(payload) - ({"registration_identifiers"} if where == "legal_entity" else set()))
    if absent:
        raise AssignmentError(f"{where} lacks required members: {', '.join(absent)}")


def _instant(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssignmentError(f"{name} is not a date-time") from exc
    if parsed.tzinfo is None:
        raise AssignmentError(f"{name} has no time zone")
    return parsed


def assignment_from_payload(payload: dict[str, Any]) -> CpErpAssignment:
    """Parse a Shared ``ErpAssignment`` body strictly: the member set is closed, so anything else is refused."""
    _closed(payload, _ASSIGNMENT_MEMBERS, "assignment")
    entity = payload["legal_entity"]
    _closed(entity, _LEGAL_ENTITY_MEMBERS, "legal_entity")
    markets = []
    for item in payload["markets"]:
        _closed(item, frozenset({"market", "activities"}), "market")
        markets.append(CpMarketAssignment(market=item["market"], activities=frozenset(item["activities"])))
    result = CpErpAssignment(
        tenant_id=payload["tenant_id"], tenant_provisioning_id=payload["tenant_provisioning_id"],
        plan_id=payload["plan_id"], plan_version=payload["plan_version"], plan_digest=payload["plan_digest"],
        legal_entity_id=entity["legal_entity_id"],
        legal_name=entity["legal_name"], jurisdiction_code=entity["jurisdiction_code"],
        registration_identifiers=tuple(dict(i) for i in entity.get("registration_identifiers", [])),
        verification_state=entity["verification_state"], markets=tuple(markets), engine_id=payload["engine_id"],
        engine_instance_id=payload["engine_instance_id"], isolation_requirement=payload["isolation_requirement"],
        capabilities=frozenset(payload["capabilities"]),
        issued_at=_instant(payload["issued_at"], "issued_at"), expires_at=_instant(payload["expires_at"], "expires_at"),
    )
    if len(result.capabilities) != len(payload["capabilities"]):
        raise AssignmentError("capabilities must be unique")
    return result
