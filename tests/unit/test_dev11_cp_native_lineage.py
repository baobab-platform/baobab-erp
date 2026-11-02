"""Negative contract tests for real CP/JVM dual-database observer.

Success-shaped rows here are fixtures to test joins, NOT a real CP decision,
real iDempiere mutation, native provider certification or L4 acceptance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from scripts.dev11_verify_cp_native_lineage import EvidenceMissing, verify

NOW = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
TENANT = "tn_dev11synthetic"
ENTITY = "LE-DEV11-SYNTHETIC"
ORG = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c"
CTX = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b"
MANDATE = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d"
DECISION = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6e"
PLACEMENT = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6f"
ORDER = "order_dev11_fixture"


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class RealDbShapeFixture:
    def __init__(self, corrupt=None):
        self.corrupt = corrupt

    def execute(self, query, params):
        if "FROM adempiere.c_order" in query:
            values = [{
                "c_order_id": 501, "ad_client_id": 11, "ad_org_id": 11,
                "poreference": ORDER, "issotrx": "Y", "docstatus": "DR",
            }]
        elif "FROM baobab_native.finance_authority_attribution" in query:
            values = [{
                "decision_id": DECISION, "context_id": CTX, "cp_mandate_id": MANDATE,
                "placement_id": PLACEMENT, "placement_version": 1,
                "tenant_id": TENANT, "operating_organisation_id": ORG,
                "responsible_legal_entity_id": ENTITY,
                "operation_class": "erp.sales-order.complete",
                "source_table": "C_Order", "source_record_id": 501,
                "ad_client_id": 11, "ad_org_id": 11,
                "finance_baseline_version": 1,
                "received_at": NOW + timedelta(seconds=5),
                "authority_expires_at": NOW + timedelta(seconds=20),
                "evidence_reference": "synthetic:fixture",
            }]
        elif "FROM registry.erp_posting_authority_decision" in query:
            values = [{
                "decision_id": DECISION, "context_id": CTX,
                "placement_id": PLACEMENT, "placement_version": 1,
                "engine_instance_id": "ei_dev11synthetic",
                "operation_class": "erp.sales-order.complete",
                "operation_reference": "erp/erp.sales-order.complete/C_Order/501/C_OrderLine/600/model:beforeSave/Trx01",
                "outcome": "AUTHORIZED", "tenant_id": TENANT,
                "operating_organisation_id": ORG, "market": "ZA",
                "legal_actor_role": "CONTRACTING_PARTY",
                "activity": "SALES_ORDER_COMMITMENT",
                "mandate_id": MANDATE, "responsible_legal_entity_id": ENTITY,
                "evaluated_at": NOW, "expires_at": NOW + timedelta(seconds=25),
                "evidence_references": ["synthetic:fixture"],
            }]
        elif "FROM context.resolved_context" in query:
            values = [{
                "tenant_id": TENANT, "authority_purpose": "RUNTIME",
                "resolved_at": NOW - timedelta(seconds=2),
                "expires_at": NOW + timedelta(seconds=300),
            }]
        elif "FROM registry.operating_legal_actor_mandate" in query:
            values = [{
                "tenant_id": TENANT, "operating_organisation_id": ORG,
                "responsible_legal_entity_id": ENTITY,
                "roles": ["CONTRACTING_PARTY"],
                "activity_scope": ["SALES_ORDER_COMMITMENT"],
                "market_scope": ["ZA"], "effective_from": NOW - timedelta(days=1),
                "approved_by": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a60",
                "created_by": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a61",
                "approved_at": NOW - timedelta(minutes=10),
                "legal_actor_verification_reference": "synthetic:fixture",
            }]
        else:
            raise AssertionError("Unexpected query in test fixture")
        if self.corrupt:
            fragment, key, replacement = self.corrupt
            if fragment in query:
                if replacement == "MISSING":
                    return Result([])
                values = [{**row, key: replacement} for row in values]
        return Result(values)


class NativeAuthorityLineageTests(unittest.TestCase):
    def check(self, erp_corrupt=None, cp_corrupt=None):
        return verify(RealDbShapeFixture(erp_corrupt),
                      RealDbShapeFixture(cp_corrupt),
                      tenant=TENANT, order=ORDER, entity=ENTITY,
                      market="ZA", client=11, org=11)

    def test_contract_checks_do_not_turn_fixture_into_l4(self):
        report = self.check()
        self.assertTrue(report["native_cp_lineage_qualified"])
        self.assertEqual(report["l4_ops_01"], "BLOCKED")
        self.assertFalse(report["protected_acceptance"])

    def test_unrecorded_or_denied_cp_decision_rejected(self):
        for corrupted in (
            ("FROM registry.erp_posting_authority_decision", "outcome", "NO_APPLICABLE_MANDATE"),
            ("FROM registry.erp_posting_authority_decision", "decision_id", "MISSING"),
            ("FROM registry.erp_posting_authority_decision", "mandate_id", "invalid"),
            ("FROM registry.erp_posting_authority_decision", "tenant_id", "tn_foreign"),
        ):
            with self.subTest(corrupted=corrupted), self.assertRaises(EvidenceMissing):
                self.check(cp_corrupt=corrupted)

    def test_non_runtime_or_foreign_context_rejected(self):
        for corrupted in (
            ("FROM context.resolved_context", "authority_purpose", "TENANT_PROVISIONING"),
            ("FROM context.resolved_context", "tenant_id", "tn_other"),
        ):
            with self.subTest(corrupted=corrupted), self.assertRaises(EvidenceMissing):
                self.check(cp_corrupt=corrupted)

    def test_missing_or_mismatched_native_jvm_attribution_rejected(self):
        for corrupted in (
            ("FROM baobab_native.finance_authority_attribution", "decision_id", "MISSING"),
            ("FROM baobab_native.finance_authority_attribution", "responsible_legal_entity_id", "LE-OTHER"),
            ("FROM baobab_native.finance_authority_attribution", "finance_baseline_version", 0),
        ):
            with self.subTest(corrupted=corrupted), self.assertRaises(EvidenceMissing):
                self.check(erp_corrupt=corrupted)

    def test_maker_checker_not_independent_rejected(self):
        with self.assertRaises(EvidenceMissing):
            self.check(cp_corrupt=(
                "FROM registry.operating_legal_actor_mandate",
                "approved_by", "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a61"))

    def test_wrong_native_company_rejected_before_cp_query(self):
        with self.assertRaises(EvidenceMissing):
            self.check(erp_corrupt=("FROM adempiere.c_order", "ad_client_id", 12))


if __name__ == "__main__":
    unittest.main()
