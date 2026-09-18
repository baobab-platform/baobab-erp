import json
from datetime import date, datetime
from pathlib import Path

from provisioning.model import (
    PENDING_DATE,
    PENDING_DATETIME,
    AccountingConfiguration,
    ErpProvisioningRequest,
    MarketConfiguration,
)

_PLACEHOLDER_PREFIX = "REQUIRED_"


def _parse_date_or_pending(value: str) -> date:
    if value.startswith(_PLACEHOLDER_PREFIX):
        return PENDING_DATE
    return date.fromisoformat(value)


def _parse_datetime_or_pending(value: str) -> datetime:
    if value.startswith(_PLACEHOLDER_PREFIX):
        return PENDING_DATETIME
    return datetime.fromisoformat(value)


def load_request(path: str | Path) -> ErpProvisioningRequest:
    """Parse a provisioning request config. This is structural parsing only --
    a config with ``REQUIRED_*`` placeholders throughout (including for
    effective_date/accounting.approved_at, which load as the PENDING_DATE/
    PENDING_DATETIME sentinels rather than raising) still loads successfully.
    Whether it's actually safe to provision from is validate_request's job,
    not this function's."""
    payload = json.loads(Path(path).read_text())
    accounting = payload["accounting"]
    return ErpProvisioningRequest(
        provisioning_id=payload["provisioning_id"],
        idempotency_key=payload["idempotency_key"],
        tenant_id=payload["tenant_id"],
        legal_entity_id=payload["legal_entity_id"],
        legal_name=payload["legal_name"],
        registration_identifier=payload["registration_identifier"],
        jurisdiction_code=payload["jurisdiction_code"],
        engine_instance_id=payload["engine_instance_id"],
        isolation_profile_id=payload["isolation_profile_id"],
        capability_binding_id=payload["capability_binding_id"],
        target_environment=payload["target_environment"],
        effective_date=_parse_date_or_pending(payload["effective_date"]),
        accounting=AccountingConfiguration(
            functional_currency=accounting["functional_currency"],
            fiscal_year_start_month=int(accounting["fiscal_year_start_month"]),
            chart_of_accounts_template=accounting["chart_of_accounts_template"],
            accounting_schema=accounting["accounting_schema"],
            tax_profile=accounting["tax_profile"],
            costing_method=accounting["costing_method"],
            approved_by=accounting["approved_by"],
            approved_at=_parse_datetime_or_pending(accounting["approved_at"]),
        ),
        markets=tuple(
            MarketConfiguration(
                market_id=item["market_id"],
                country_code=item["country_code"],
                participation_capabilities=frozenset(item["participation_capabilities"]),
                currencies=tuple(item["currencies"]),
                localisation_profile=item["localisation_profile"],
                warehouse_codes=tuple(item.get("warehouse_codes", ())),
            )
            for item in payload["markets"]
        ),
        requested_capabilities=frozenset(payload["requested_capabilities"]),
    )
