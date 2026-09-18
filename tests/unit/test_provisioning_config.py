import json
import tempfile
import unittest
from pathlib import Path

from provisioning.config import load_request
from provisioning.model import PENDING_DATE, PENDING_DATETIME
from provisioning.planner import build_plan
from test_provisioning_planner import valid_request

_REPO_ROOT = Path(__file__).resolve().parents[2]


class ProvisioningConfigTests(unittest.TestCase):
    def test_loads_json_desired_state(self):
        request = valid_request()
        payload = {
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
            "target_environment": request.target_environment,
            "effective_date": request.effective_date.isoformat(),
            "requested_capabilities": sorted(request.requested_capabilities),
            "accounting": {
                "functional_currency": request.accounting.functional_currency,
                "fiscal_year_start_month": request.accounting.fiscal_year_start_month,
                "chart_of_accounts_template": request.accounting.chart_of_accounts_template,
                "accounting_schema": request.accounting.accounting_schema,
                "tax_profile": request.accounting.tax_profile,
                "costing_method": request.accounting.costing_method,
                "approved_by": request.accounting.approved_by,
                "approved_at": request.accounting.approved_at.isoformat(),
            },
            "markets": [{
                "market_id": request.markets[0].market_id,
                "country_code": request.markets[0].country_code,
                "participation_capabilities": sorted(request.markets[0].participation_capabilities),
                "currencies": list(request.markets[0].currencies),
                "localisation_profile": request.markets[0].localisation_profile,
                "warehouse_codes": list(request.markets[0].warehouse_codes),
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desired.json"
            path.write_text(json.dumps(payload))
            loaded = load_request(path)
        self.assertEqual(build_plan(loaded), build_plan(request))

    def test_placeholder_effective_date_and_approved_at_load_as_pending_sentinels(self):
        # Regression test: these two fields are typed date/datetime, so a raw
        # "REQUIRED_*" placeholder string used to raise ValueError out of
        # date.fromisoformat()/datetime.fromisoformat() before validate_request
        # ever got a chance to report it as a normal "missing or placeholder"
        # readiness check, the same way every other REQUIRED_* field does.
        request = valid_request()
        payload = {
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
            "target_environment": request.target_environment,
            "effective_date": "REQUIRED_APPROVED_EFFECTIVE_DATE",
            "requested_capabilities": sorted(request.requested_capabilities),
            "accounting": {
                "functional_currency": request.accounting.functional_currency,
                "fiscal_year_start_month": request.accounting.fiscal_year_start_month,
                "chart_of_accounts_template": request.accounting.chart_of_accounts_template,
                "accounting_schema": request.accounting.accounting_schema,
                "tax_profile": request.accounting.tax_profile,
                "costing_method": request.accounting.costing_method,
                "approved_by": request.accounting.approved_by,
                "approved_at": "REQUIRED_APPROVAL_TIMESTAMP",
            },
            "markets": [{
                "market_id": request.markets[0].market_id,
                "country_code": request.markets[0].country_code,
                "participation_capabilities": sorted(request.markets[0].participation_capabilities),
                "currencies": list(request.markets[0].currencies),
                "localisation_profile": request.markets[0].localisation_profile,
                "warehouse_codes": list(request.markets[0].warehouse_codes),
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending.json"
            path.write_text(json.dumps(payload))
            loaded = load_request(path)  # must not raise
        self.assertEqual(loaded.effective_date, PENDING_DATE)
        self.assertEqual(loaded.accounting.approved_at, PENDING_DATETIME)

    def test_zuribeans_ug_and_za_templates_load(self):
        for market in ("ug", "za"):
            path = _REPO_ROOT / "config" / "provisioning" / f"zuribeans-{market}.production.template.json"
            request = load_request(path)  # must not raise
            self.assertEqual(request.jurisdiction_code, market.upper())
            self.assertEqual(len(request.markets), 1)
            self.assertEqual(request.markets[0].country_code, market.upper())


if __name__ == "__main__":
    unittest.main()
