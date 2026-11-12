"""ADR-ERP-009: protected market provisioning cannot consume a draft file.

This is a configuration-status fail-closed guard only. A string saying
"approved" does not confer CP/Finance/localisation legal-actor authority.
"""
from __future__ import annotations

import unittest

from provisioning.market_configuration import MarketConfigurationError, parse_deployment_configuration


def config(*, environment="production", status="draft-not-approved"):
    return {
        "schema_version": "1.0",
        "status": status,
        "target_environment": environment,
        "markets": {
            "ZA": {
                "currencies": ["ZAR"],
                "localisation_profile": "za-candidate-v1",
                "warehouse_codes": ["JNB"],
                "warehouse_timezones": {"JNB": "Africa/Johannesburg"},
            }
        },
        "native_placements": {
            "ZURIBEANS-ZA": {"native_client_key": "ZB-ZA-01"}
        },
    }


class MarketConfigurationApprovalTests(unittest.TestCase):
    def test_protected_runtime_denies_a_filled_but_unapproved_localisation_template(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(MarketConfigurationError, "not approved"):
                    parse_deployment_configuration(config(environment=environment))

    def test_missing_and_unknown_status_is_not_silently_accepted(self):
        for status in (None, "", "REQUIRED_APPROVAL", "approved-now", "ACTIVE"):
            with self.subTest(status=status):
                with self.assertRaises(MarketConfigurationError):
                    parse_deployment_configuration(config(status=status))

    def test_declared_approved_protected_configuration_still_has_no_mandate(self):
        result = parse_deployment_configuration(config(status="approved"))
        self.assertEqual(result.target_environment, "production")
        self.assertEqual(result.markets["ZA"].currencies, ("ZAR",))
        # This parser does not qualify a Finance or tax profile, nor grant a
        # CP operation. Those later security/finance gates stay authoritative.
        self.assertIsNotNone(result.native_placement)

    def test_local_development_can_parse_a_draft_without_promoting_it(self):
        result = parse_deployment_configuration(config(environment="development"))
        self.assertEqual(result.target_environment, "development")


if __name__ == "__main__":
    unittest.main()
