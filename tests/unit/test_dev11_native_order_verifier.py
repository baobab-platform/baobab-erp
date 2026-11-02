"""DEV-11 native readback verifier fail-closed unit tests.

The fake SQL responses here test verifier semantics only. Native iDempiere
business execution MUST be independently observed in a real PostgreSQL test;
these mocks are NEVER business-effect acceptance.
"""
from __future__ import annotations
import unittest

from scripts.dev11_verify_native_idempiere_order import NotProven, verify

TENANT = "tn_dev11synthetic"
EVENT_ID = "1d032305-669c-45df-b988-01166de4c14c"
ORDER_ID = "order_dev11_synthetic"
LEGAL = "LE-DEV11-SYNTHETIC"


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class FakeDatabase:
    def __init__(self, *, fail=None):
        self.fail = fail

    def execute(self, query, params):
        if self.fail and self.fail in query:
            # COUNT probes return an actual zero row; SELECT * probes return
            # no rows. Test the verifier, not an IndexError in this fixture.
            return FakeResult([(0,)] if "SELECT count(*)" in query else [])
        if "FROM baobab.event_inbox" in query:
            return FakeResult([(
                "processed", "EXECUTED",
                "com.baobab-platform.trade.order.placed.v1",
                TENANT, {
                    "commerce_order_id": ORDER_ID,
                    "legal_entity_id": LEGAL,
                    "order_version": 1,
                    "lines": [{"line_id": "line_01"}],
                }, "dev11-rabbit-connected:" + EVENT_ID,
            )])
        if "FROM baobab.order_execution" in query:
            return FakeResult([(LEGAL, 1, "C_Order", 120, EVENT_ID, "erp_dev11order", False)])
        if "FROM adempiere.c_order " in query:
            return FakeResult([(120, 11, 11, ORDER_ID, "DR")])
        if "FROM adempiere.c_orderline" in query:
            return FakeResult([(1, 1, 0)])
        if "FROM baobab.order_consequence" in query:
            return FakeResult([(LEGAL, 1, "erp_dev11order", "accepted", 1, "pending")])
        if "FROM baobab.event_outbox" in query:
            return FakeResult([(1,)])
        if "FROM baobab_native.native_placement" in query:
            return FakeResult([(1,)])
        if "FROM baobab_native.finance_authority_attribution" in query:
            return FakeResult([(1,)])
        raise AssertionError("Unrecognised SQL in test fixture")


class NativeReadbackSafetyTests(unittest.TestCase):
    def test_structurally_complete_observations_still_cannot_certify_l4(self):
        observed = verify(FakeDatabase(), TENANT, EVENT_ID, LEGAL, 11, 11)
        self.assertTrue(observed["native_order_effect_qualified"])
        self.assertEqual(observed["l4_ops_01"], "BLOCKED")
        self.assertFalse(observed["financial_posting_inferred"])

    def test_missing_native_jvm_cp_mandate_attribution_denied(self):
        with self.assertRaisesRegex(
                NotProven, "NATIVE_JVM_AUTHORITY_ATTRIBUTION_MISSING"):
            verify(FakeDatabase(fail="FROM baobab_native.finance_authority_attribution"),
                   TENANT, EVENT_ID, LEGAL, 11, 11)

    def test_missing_real_native_order_denied(self):
        with self.assertRaisesRegex(NotProven, "IDEMPIERE_ORDER_MISSING"):
            verify(FakeDatabase(fail="FROM adempiere.c_order "), TENANT, EVENT_ID, LEGAL, 11, 11)

    def test_missing_erp_receipt_denied(self):
        with self.assertRaisesRegex(NotProven, "NATIVE_INBOX_NOT_UNIQUE"):
            verify(FakeDatabase(fail="FROM baobab.event_inbox"), TENANT, EVENT_ID, LEGAL, 11, 11)

    def test_missing_erp_outbox_denied(self):
        with self.assertRaises(NotProven):
            verify(FakeDatabase(fail="FROM baobab.event_outbox"), TENANT, EVENT_ID, LEGAL, 11, 11)

    def test_wrong_company_denied_even_when_order_exists(self):
        with self.assertRaisesRegex(NotProven, "IDEMPIERE_ORDER_FOREIGN"):
            verify(FakeDatabase(), TENANT, EVENT_ID, LEGAL, 12, 11)

    def test_wrong_native_org_denied_even_when_order_exists(self):
        with self.assertRaisesRegex(NotProven, "IDEMPIERE_ORDER_FOREIGN"):
            verify(FakeDatabase(), TENANT, EVENT_ID, LEGAL, 11, 12)

    def test_invalid_source_event_and_scope_rejected_pre_query(self):
        for eid, tenant in (("invalid", TENANT), (EVENT_ID, "other")):
            with self.subTest(eid=eid, tenant=tenant):
                with self.assertRaises(NotProven):
                    verify(FakeDatabase(), tenant, eid, LEGAL, 11, 11)


if __name__ == "__main__":
    unittest.main()
