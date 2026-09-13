from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any


class ProvisioningStatus(StrEnum):
    REQUESTED = "requested"
    VALIDATING = "validating"
    PLANNED = "planned"
    APPLYING = "applying"
    RECONCILING = "reconciling"
    READY = "ready"
    ACTIVE = "active"
    FAILED = "failed"
    SUSPENDED = "suspended"


class StepKind(StrEnum):
    CREATE_CLIENT = "create_client"
    CREATE_ORGANISATION = "create_organisation"
    CONFIGURE_ACCOUNTING = "configure_accounting"
    CONFIGURE_LOCALISATION = "configure_localisation"
    CREATE_WAREHOUSE = "create_warehouse"
    PERSIST_MAPPING = "persist_mapping"


@dataclass(frozen=True, slots=True)
class MarketConfiguration:
    market_id: str
    country_code: str
    participation_capabilities: frozenset[str]
    currencies: tuple[str, ...]
    localisation_profile: str
    warehouse_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AccountingConfiguration:
    functional_currency: str
    fiscal_year_start_month: int
    chart_of_accounts_template: str
    accounting_schema: str
    tax_profile: str
    costing_method: str
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class ErpProvisioningRequest:
    provisioning_id: str
    idempotency_key: str
    tenant_id: str
    legal_entity_id: str
    legal_name: str
    registration_identifier: str
    jurisdiction_code: str
    engine_instance_id: str
    isolation_profile_id: str
    capability_binding_id: str
    target_environment: str
    effective_date: date
    accounting: AccountingConfiguration
    markets: tuple[MarketConfiguration, ...]
    requested_capabilities: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ProvisioningStep:
    key: str
    kind: StepKind
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProvisioningPlan:
    provisioning_id: str
    desired_state_digest: str
    steps: tuple[ProvisioningStep, ...]


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    code: str
    ready: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ProvisioningReadiness:
    provisioning_id: str
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(check.ready for check in self.checks)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
