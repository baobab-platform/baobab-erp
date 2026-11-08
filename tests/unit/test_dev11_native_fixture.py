"""Relational selector regressions; these do not qualify native ERP effects.

SQLite exercises the ANSI customer/location predicates with actual rows.
PostgreSQL 17, CP and the protected JVM remain mandatory connected gates.
"""
from pathlib import Path
from decimal import Decimal
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from types import SimpleNamespace

DRIVER = Path(__file__).resolve().parents[2] / "idempiere/acceptance/erp-a/driver"
sys.path.insert(0, str(DRIVER))
try:
    from dev11_native_connected import (inspect_outcome, inspect_cp_sales_decision,
                                       inspect_cp_documentary_decision, native_customer,
                                       native_id, fixture_order_reference, run_independent_observer)
finally:
    sys.path.remove(str(DRIVER))


class NativeCustomerSelectorTests(unittest.TestCase):
    def test_synthetic_order_keeps_full_identity_beyond_legacy_reference_width(self):
        reference = fixture_order_reference()
        self.assertEqual(len(reference), 38)
        self.assertRegex(reference, r"^order_[0-9a-f]{32}$")

    def test_observer_refusal_never_discloses_private_command_arguments(self):
        import subprocess
        for failure in (subprocess.TimeoutExpired(["private-event", "private-tenant"], 1),
                        OSError("private-event private-tenant"), None):
            with self.subTest(failure=type(failure).__name__), patch(
                    "dev11_native_connected.subprocess.run", side_effect=failure,
                    return_value=SimpleNamespace(returncode=2)):
                with self.assertRaises(RuntimeError) as raised:
                    run_independent_observer(["private-event", "private-tenant"],
                                             env={}, stage="NATIVE")
                self.assertNotIn("private-", str(raised.exception))
                self.assertIn("NATIVE", str(raised.exception))

    def test_native_outcome_diagnostic_never_emits_provider_text(self):
        class Row:
            def execute(self, *_):
                return self

            def fetchone(self):
                return ("retry", "private-provider-text/token=not-public")

        out = StringIO()
        with redirect_stdout(out), self.assertRaisesRegex(
                RuntimeError, "^DEV11_REAL_NATIVE_ORDER_NOT_EXECUTED$"):
            inspect_outcome(Row(), "synthetic-event-only", allowed=True)
        self.assertIn('"code": "UNCLASSIFIED"', out.getvalue())
        self.assertNotIn("private-provider-text", out.getvalue())
        self.assertNotIn("synthetic-event-only", out.getvalue())

    def test_cp_preflight_never_treats_malformed_or_unbound_reply_as_authority(self):
        context, order = "context-from-cp", "order-from-trade"
        good = {
            "context_id": context, "operation_reference": order,
            "provider_permissions_granted": False,
            "legal_actor_resolution": {"outcome": "AUTHORIZED"},
            # Untrusted extra response properties must never be emitted by
            # the diagnostic receipt as tenant, buyer, token or mandate.
            "secret_access_token": "must-not-be-reported",
        }
        read = lambda status, body: inspect_cp_sales_decision(
            SimpleNamespace(status=status, body=body),
            context_id=context, order_reference=order)
        self.assertEqual(read(200, good), {
            "http_ok": True, "decision": "AUTHORIZED",
            "exact_operation": True, "provider_permissions": True})
        for status, data in (
                (403, good),
                (200, {**good, "context_id": "other"}),
                (200, {**good, "operation_reference": "other"}),
                (200, {**good, "legal_actor_resolution":
                       {"outcome": "ACTOR_NOT_VERIFIED"}}),
                (200, {**good, "legal_actor_resolution":
                       {"outcome": "INVENTED_ALLOW"}}),
                (200, {**good, "provider_permissions_granted": True}),
                (200, []),
        ):
            with self.subTest(status=status, body=data):
                result = read(status, data)
                self.assertFalse(
                    result["http_ok"] and result["decision"] == "AUTHORIZED"
                    and result["exact_operation"] and result["provider_permissions"])
                self.assertNotIn("secret_access_token", str(result))
                self.assertNotIn("must-not-be-reported", str(result))

    def test_documentary_preflight_is_negative_only_and_exactly_scoped(self):
        context, organisation, order, market, capability = (
            "cp-context", "cp-organisation", "order-native", "US", "erp.erp-a")
        good = {
            "context_id": context, "organisation_id": organisation,
            "operation_reference": order, "market": market,
            "capability": capability,
            "policy_reference": "ADR-BCP-026/PEO-02T:negative-only",
            "blocked": False, "authority_granted": False,
            "private_bearer": "never-export",
        }
        def read(status, body):
            return inspect_cp_documentary_decision(
                SimpleNamespace(status=status, body=body),
                context_id=context, organisation_id=organisation,
                order_reference=order, market=market, capability=capability)
        expected = {"http_ok": True, "exact_operation": True,
                    "unblocked": True, "negative_only": True}
        self.assertEqual(read(200, good), expected)
        for status, body in (
                (403, good),
                (200, {**good, "blocked": True}),
                (200, {**good, "authority_granted": True}),
                (200, {**good, "context_id": "other"}),
                (200, {**good, "organisation_id": "other"}),
                (200, {**good, "operation_reference": "another-order"}),
                (200, {**good, "market": "ZA"}),
                (200, {**good, "capability": "erp.other"}),
                (200, {**good, "policy_reference": "not-a-policy"}),
                (200, []),
        ):
            with self.subTest(status=status, body=body):
                actual = read(status, body)
                self.assertFalse(all(actual.values()))
                self.assertNotIn("private_bearer", str(actual))
                self.assertNotIn("never-export", str(actual))

    def test_exact_native_numeric_ids_without_coercion(self):
        for value in (101, Decimal("101"), Decimal("101.000")):
            self.assertEqual(native_id(value, "NOT_READY"), 101)
        for value in (None, True, False, "101", 101.0, Decimal("1.1"),
                      Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"),
                      Decimal("0"), -1, Decimal("2147483648"), Decimal("1e1000")):
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(RuntimeError, "^NOT_READY$"):
                    native_id(value, "NOT_READY")

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS adempiere")
        self.db.execute("""CREATE TABLE adempiere.c_bpartner (
            c_bpartner_id INTEGER, ad_client_id INTEGER, ad_org_id INTEGER,
            iscustomer TEXT, isactive TEXT)""")
        self.db.execute("""CREATE TABLE adempiere.c_bpartner_location (
            c_bpartner_id INTEGER, isactive TEXT, isbillto TEXT, isshipto TEXT)""")

    def partner(self, *, client=11, org=11, active="Y", customer="Y"):
        self.db.execute("INSERT INTO adempiere.c_bpartner VALUES (101,?,?,?,?)",
                        (client, org, customer, active))

    def location(self, billing, shipping, active="Y"):
        self.db.execute("INSERT INTO adempiere.c_bpartner_location VALUES (101,?,?,?)",
                        (active, billing, shipping))

    def test_separate_billing_and_shipping_locations_are_usable(self):
        self.partner()
        self.location("Y", "N")
        self.location("N", "Y")
        self.assertEqual(native_customer(self.db), 101)

    def test_shared_billing_and_shipping_location_is_usable(self):
        self.partner(org=0)
        self.location("Y", "Y")
        self.assertEqual(native_customer(self.db), 101)

    def test_customer_and_location_boundaries_remain_closed(self):
        for defect in ("foreign-client", "foreign-org", "inactive-customer",
                       "not-customer", "no-billing", "no-shipping", "inactive-location"):
            with self.subTest(defect=defect):
                self.db.execute("DELETE FROM adempiere.c_bpartner")
                self.db.execute("DELETE FROM adempiere.c_bpartner_location")
                self.partner(client=12 if defect == "foreign-client" else 11,
                             org=12 if defect == "foreign-org" else 11,
                             active="N" if defect == "inactive-customer" else "Y",
                             customer="N" if defect == "not-customer" else "Y")
                self.location("N" if defect == "no-billing" else "Y",
                              "N" if defect == "no-shipping" else "Y",
                              "N" if defect == "inactive-location" else "Y")
                self.assertIsNone(native_customer(self.db))


if __name__ == "__main__":
    unittest.main()
