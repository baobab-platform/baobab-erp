import unittest
from dataclasses import replace
from datetime import date, datetime, timezone

from provisioning.model import AccountingConfiguration, ErpProvisioningRequest, MarketConfiguration
from provisioning.planner import build_plan
from provisioning.validation import InvalidProvisioningRequestError


def valid_request() -> ErpProvisioningRequest:
    return ErpProvisioningRequest(
        provisioning_id="zb-v1", idempotency_key="zb-v1", tenant_id="tenant-zb",
        legal_entity_id="le-zb", legal_name="ZuriBeans Ltd", registration_identifier="reg-1",
        jurisdiction_code="UG", engine_instance_id="erp-af-south-01",
        isolation_requirement="row_level_security", plan_digest="sha256:" + "b2" * 32,
        target_environment="production", effective_date=date(2026, 10, 1),
        accounting=AccountingConfiguration("UGX", 1, "coa-zb-v1", "ZB Primary", "tax-ug-v1", "average-po", "finance-user", datetime(2026, 9, 13, tzinfo=timezone.utc)),
        markets=(MarketConfiguration("market-ug", "UG", frozenset({"sourcing", "selling"}), ("UGX", "USD"), "ug-v1", ("KLA",)),),
        requested_capabilities=frozenset({"finance.order-consequence.process"}),
    )


class ProvisioningPlannerTests(unittest.TestCase):
    def test_plan_is_deterministic(self):
        first = build_plan(valid_request())
        second = build_plan(valid_request())
        self.assertEqual(first, second)
        self.assertEqual(len({step.key for step in first.steps}), len(first.steps))

    def test_plan_contains_financial_localisation_warehouse_and_mapping_steps(self):
        kinds = {step.kind.value for step in build_plan(valid_request()).steps}
        self.assertTrue({"create_client", "configure_accounting", "configure_localisation", "create_warehouse", "persist_mapping"} <= kinds)

    def test_unsupported_capability_fails_closed(self):
        # ERP, not Control Plane, decides which canonical capabilities this release can honour.
        request = replace(valid_request(), requested_capabilities=frozenset({"finance.order-consequence.process", "commerce.order.manage"}))
        with self.assertRaises(InvalidProvisioningRequestError):
            build_plan(request)

    def test_no_capability_fails_closed(self):
        with self.assertRaises(InvalidProvisioningRequestError):
            build_plan(replace(valid_request(), requested_capabilities=frozenset()))

    def test_isolation_requirement_outside_the_canonical_vocabulary_fails_closed(self):
        with self.assertRaises(InvalidProvisioningRequestError):
            build_plan(replace(valid_request(), isolation_requirement="iso-client"))

    def test_the_mapping_step_records_the_approved_plan_not_a_registry_identifier(self):
        step = next(step for step in build_plan(valid_request()).steps if step.kind.value == "persist_mapping")
        self.assertEqual(step.payload["plan_digest"], valid_request().plan_digest)
        self.assertNotIn("capability_binding_id", step.payload)

    def test_placeholder_control_plane_ids_fail_closed(self):
        request = replace(valid_request(), tenant_id="REQUIRED_CP_TENANT_ID")
        with self.assertRaises(InvalidProvisioningRequestError):
            build_plan(request)


if __name__ == "__main__":
    unittest.main()
