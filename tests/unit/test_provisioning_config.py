import json
import tempfile
import unittest
from pathlib import Path

from provisioning.config import load_request
from provisioning.planner import build_plan
from test_provisioning_planner import valid_request


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


if __name__ == "__main__":
    unittest.main()
