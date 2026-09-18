import hashlib
import json
from dataclasses import asdict

from provisioning.model import ErpProvisioningRequest, ProvisioningPlan, ProvisioningStep, StepKind
from provisioning.validation import require_valid_request


def _json_default(value):
    if isinstance(value, (frozenset, set)):
        # sort, don't just list(): frozenset iteration order depends on element
        # hashes AND insertion/resize history, so two frozensets with identical
        # elements built via different code paths (e.g. a literal here vs
        # frozenset(sorted(...)) after a JSON round-trip in config.py) are not
        # guaranteed to iterate identically even within one interpreter process.
        # str()/list() on the set directly would make this function's digest --
        # and therefore step keys -- silently non-deterministic for the exact
        # same desired state, defeating this function's own documented guarantee.
        return sorted(value)
    return str(value)


def build_plan(request: ErpProvisioningRequest) -> ProvisioningPlan:
    """Create a deterministic plan. The same desired state produces the same
    digest and step keys, which makes retries safe and reviewable."""
    require_valid_request(request)
    serialised = json.dumps(asdict(request), sort_keys=True, default=_json_default, separators=(",", ":"))
    digest = hashlib.sha256(serialised.encode()).hexdigest()
    prefix = f"{request.provisioning_id}:{digest[:12]}"
    steps: list[ProvisioningStep] = [
        ProvisioningStep(f"{prefix}:client", StepKind.CREATE_CLIENT, {"Name": request.legal_name}),
        ProvisioningStep(
            f"{prefix}:accounting",
            StepKind.CONFIGURE_ACCOUNTING,
            {
                "functional_currency": request.accounting.functional_currency,
                "accounting_schema": request.accounting.accounting_schema,
                "chart_of_accounts_template": request.accounting.chart_of_accounts_template,
                "fiscal_year_start_month": request.accounting.fiscal_year_start_month,
                "tax_profile": request.accounting.tax_profile,
                "costing_method": request.accounting.costing_method,
            },
        ),
    ]
    for market in sorted(request.markets, key=lambda item: item.market_id):
        steps.append(
            ProvisioningStep(
                f"{prefix}:market:{market.market_id}",
                StepKind.CONFIGURE_LOCALISATION,
                {"market_id": market.market_id, "country_code": market.country_code, "profile": market.localisation_profile},
            )
        )
        for warehouse in sorted(market.warehouse_codes):
            steps.append(
                ProvisioningStep(
                    f"{prefix}:warehouse:{market.market_id}:{warehouse}",
                    StepKind.CREATE_WAREHOUSE,
                    {"market_id": market.market_id, "warehouse_code": warehouse},
                )
            )
    steps.append(
        ProvisioningStep(
            f"{prefix}:mapping",
            StepKind.PERSIST_MAPPING,
            {
                "tenant_id": request.tenant_id,
                "legal_entity_id": request.legal_entity_id,
                "engine_instance_id": request.engine_instance_id,
                "capability_binding_id": request.capability_binding_id,
            },
        )
    )
    return ProvisioningPlan(request.provisioning_id, digest, tuple(steps))
