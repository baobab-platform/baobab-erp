from provisioning.model import ErpProvisioningRequest, ReadinessCheck


_REQUIRED_CAPABILITIES = frozenset(
    {
        "erp.accounting",
        "erp.accounts-payable",
        "erp.accounts-receivable",
        "erp.inventory",
        "erp.procurement",
    }
)
_MARKET_CAPABILITIES = frozenset(
    {"sourcing", "procurement", "selling", "warehousing", "distribution", "importing", "exporting"}
)


class InvalidProvisioningRequestError(ValueError):
    pass


def validate_request(request: ErpProvisioningRequest) -> tuple[ReadinessCheck, ...]:
    checks: list[ReadinessCheck] = []
    required_text = {
        "provisioning_id": request.provisioning_id,
        "idempotency_key": request.idempotency_key,
        "tenant_id": request.tenant_id,
        "legal_entity_id": request.legal_entity_id,
        "legal_name": request.legal_name,
        "registration_identifier": request.registration_identifier,
        "jurisdiction_code": request.jurisdiction_code,
        "engine_instance_id": request.engine_instance_id,
        "isolation_profile_id": request.isolation_profile_id,
        "capability_binding_id": request.capability_binding_id,
        "accounting.approved_by": request.accounting.approved_by,
    }
    for name, value in required_text.items():
        valid = bool(value.strip()) and not value.startswith("REQUIRED_")
        checks.append(ReadinessCheck(f"required.{name}", valid, "configured" if valid else "missing or placeholder"))

    checks.append(
        ReadinessCheck(
            "environment.production",
            request.target_environment == "production",
            f"target={request.target_environment}",
        )
    )
    accounting_values = {
        "functional_currency": request.accounting.functional_currency,
        "chart_of_accounts_template": request.accounting.chart_of_accounts_template,
        "accounting_schema": request.accounting.accounting_schema,
        "tax_profile": request.accounting.tax_profile,
        "costing_method": request.accounting.costing_method,
    }
    for name, value in accounting_values.items():
        valid = bool(value.strip()) and not value.startswith("REQUIRED_")
        checks.append(ReadinessCheck(f"accounting.{name}", valid, "configured" if valid else "missing or placeholder"))
    missing = sorted(_REQUIRED_CAPABILITIES - request.requested_capabilities)
    checks.append(ReadinessCheck("capabilities.release1", not missing, "complete" if not missing else f"missing: {', '.join(missing)}"))
    checks.append(
        ReadinessCheck(
            "accounting.fiscal_year",
            1 <= request.accounting.fiscal_year_start_month <= 12,
            f"start_month={request.accounting.fiscal_year_start_month}",
        )
    )
    checks.append(
        ReadinessCheck(
            "accounting.approval",
            bool(request.accounting.approved_by.strip()),
            "finance approval recorded" if request.accounting.approved_by.strip() else "finance approval required",
        )
    )
    market_ids: set[str] = set()
    for market in request.markets:
        unique = market.market_id not in market_ids
        market_ids.add(market.market_id)
        checks.append(ReadinessCheck(f"market.{market.market_id}.unique", unique, "unique" if unique else "duplicate"))
        unknown = sorted(market.participation_capabilities - _MARKET_CAPABILITIES)
        checks.append(ReadinessCheck(f"market.{market.market_id}.capabilities", not unknown, "valid" if not unknown else f"unknown: {', '.join(unknown)}"))
        localisation_valid = bool(market.localisation_profile) and not market.localisation_profile.startswith("REQUIRED_")
        checks.append(ReadinessCheck(f"market.{market.market_id}.localisation", localisation_valid, market.localisation_profile or "missing"))
        currencies_valid = bool(market.currencies) and all(len(code) == 3 and code.isupper() for code in market.currencies)
        checks.append(ReadinessCheck(f"market.{market.market_id}.currencies", currencies_valid, ",".join(market.currencies) or "missing"))
        warehouses_valid = bool(market.warehouse_codes) and all(not code.startswith("REQUIRED_") for code in market.warehouse_codes)
        checks.append(ReadinessCheck(f"market.{market.market_id}.warehouses", warehouses_valid, ",".join(market.warehouse_codes) or "missing"))
    return tuple(checks)


def require_valid_request(request: ErpProvisioningRequest) -> tuple[ReadinessCheck, ...]:
    checks = validate_request(request)
    failures = [check for check in checks if not check.ready]
    if failures:
        raise InvalidProvisioningRequestError("; ".join(f"{item.code}: {item.detail}" for item in failures))
    return checks
