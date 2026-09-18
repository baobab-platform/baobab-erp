from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from provisioning.model import AccountingConfiguration, ErpProvisioningRequest, MarketConfiguration


class AssignmentError(ValueError):
    pass


class NativeClientMode(StrEnum):
    DEDICATED_CLIENT = "dedicated_client"
    EXISTING_CLIENT = "existing_client"


@dataclass(frozen=True, slots=True)
class CpMarketAssignment:
    market_id: str
    country_code: str
    capabilities: frozenset[str]
    currencies: tuple[str, ...]
    localisation_profile: str
    warehouse_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CpErpAssignment:
    """Authoritative CP projection consumed by baobab-erp.

    CP remains authority for canonical IDs, topology and isolation. ERP must not
    infer an EngineInstance, CapabilityBinding, LegalEntity or isolation profile.
    """
    assignment_version: str
    provisioning_id: str
    idempotency_key: str
    tenant_id: str
    legal_entity_id: str
    legal_entity_code: str
    legal_name: str
    registration_identifier: str
    jurisdiction_code: str
    engine_instance_id: str
    isolation_profile_id: str
    capability_binding_id: str
    target_environment: str
    effective_date: date
    native_client_mode: NativeClientMode
    native_client_key: str
    markets: tuple[CpMarketAssignment, ...]
    requested_capabilities: frozenset[str]
    issued_at: datetime
    expires_at: datetime | None = None

    def validate(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        required = {
            "assignment_version": self.assignment_version,
            "provisioning_id": self.provisioning_id,
            "idempotency_key": self.idempotency_key,
            "tenant_id": self.tenant_id,
            "legal_entity_id": self.legal_entity_id,
            "legal_entity_code": self.legal_entity_code,
            "legal_name": self.legal_name,
            "engine_instance_id": self.engine_instance_id,
            "isolation_profile_id": self.isolation_profile_id,
            "capability_binding_id": self.capability_binding_id,
            "native_client_key": self.native_client_key,
        }
        missing = [k for k, v in required.items() if not str(v).strip()]
        if missing:
            raise AssignmentError(f"missing authoritative assignment fields: {', '.join(missing)}")
        if self.target_environment != "production":
            raise AssignmentError(f"ERP production provisioning requires production, got {self.target_environment!r}")
        if self.expires_at is not None and now >= self.expires_at:
            raise AssignmentError("authoritative CP assignment has expired")
        if not self.markets:
            raise AssignmentError("at least one CP-authorised market assignment is required")
        market_ids = [m.market_id for m in self.markets]
        if len(market_ids) != len(set(market_ids)):
            raise AssignmentError("duplicate market_id in CP assignment")


class ControlPlaneAssignmentSource(Protocol):
    def resolve_erp_assignment(
        self, *, tenant_id: str, legal_entity_id: str, capability_key: str
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


def materialize_request(
    assignment: CpErpAssignment,
    accounting: FinanceBaseline,
) -> ErpProvisioningRequest:
    assignment.validate()
    return ErpProvisioningRequest(
        provisioning_id=assignment.provisioning_id,
        idempotency_key=assignment.idempotency_key,
        tenant_id=assignment.tenant_id,
        legal_entity_id=assignment.legal_entity_id,
        legal_name=assignment.legal_name,
        registration_identifier=assignment.registration_identifier,
        jurisdiction_code=assignment.jurisdiction_code,
        engine_instance_id=assignment.engine_instance_id,
        isolation_profile_id=assignment.isolation_profile_id,
        capability_binding_id=assignment.capability_binding_id,
        target_environment=assignment.target_environment,
        effective_date=assignment.effective_date,
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
        markets=tuple(
            MarketConfiguration(
                market_id=m.market_id,
                country_code=m.country_code,
                participation_capabilities=m.capabilities,
                currencies=m.currencies,
                localisation_profile=m.localisation_profile,
                warehouse_codes=m.warehouse_codes,
            )
            for m in assignment.markets
        ),
        requested_capabilities=assignment.requested_capabilities,
    )


def assignment_from_payload(payload: dict[str, Any]) -> CpErpAssignment:
    markets = tuple(
        CpMarketAssignment(
            market_id=m["market_id"],
            country_code=m["country_code"],
            capabilities=frozenset(m["capabilities"]),
            currencies=tuple(m["currencies"]),
            localisation_profile=m["localisation_profile"],
            warehouse_codes=tuple(m.get("warehouse_codes", ())),
        )
        for m in payload["markets"]
    )
    result = CpErpAssignment(
        assignment_version=payload["assignment_version"],
        provisioning_id=payload["provisioning_id"],
        idempotency_key=payload["idempotency_key"],
        tenant_id=payload["tenant_id"],
        legal_entity_id=payload["legal_entity_id"],
        legal_entity_code=payload["legal_entity_code"],
        legal_name=payload["legal_name"],
        registration_identifier=payload["registration_identifier"],
        jurisdiction_code=payload["jurisdiction_code"],
        engine_instance_id=payload["engine_instance_id"],
        isolation_profile_id=payload["isolation_profile_id"],
        capability_binding_id=payload["capability_binding_id"],
        target_environment=payload["target_environment"],
        effective_date=date.fromisoformat(payload["effective_date"]),
        native_client_mode=NativeClientMode(payload["native_client_mode"]),
        native_client_key=payload["native_client_key"],
        markets=markets,
        requested_capabilities=frozenset(payload["requested_capabilities"]),
        issued_at=datetime.fromisoformat(payload["issued_at"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]) if payload.get("expires_at") else None,
    )
    result.validate()
    return result
