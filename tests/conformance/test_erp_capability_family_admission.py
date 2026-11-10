"""ERP capability admission guard: planning must not become CP provider support.

Accepted ADR-SHARED-033 F1 keys and ADR-SHARED-045 People keys are
canonical but NOT implemented in this engine. WMS #452 is CONTRACTING;
F2/F3 are accepted planning inventory only. Source-only tests do not confer
EA-09 certification or accountant/market approvals.
"""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = yaml.safe_load((ROOT / ".baobab/capability-provider.yaml").read_text())
F1 = {"finance.journal.manage", "finance.ledger.read", "finance.statement.read"}
F2 = {"finance.payable.manage", "finance.receivable.manage", "finance.bank-reconciliation.manage",
      "finance.cash-position.read", "finance.expense.manage", "finance.budget.manage"}
F3 = {"finance.reporting-export.create", "finance.project-cost.read", "finance.consolidation.run"}
PEOPLE = {"payroll.evidence.attest", "payroll.run.read", "workforce.employment.manage", "workforce.employment.read"}
WMS = {"inventory.custody.read", "inventory.warehouse-operation.manage"}


class CapabilityAdmissionTests(unittest.TestCase):
    def test_only_real_existing_erp_implementations_are_supported(self):
        actual = {x["capability_key"]: x["implementation_status"] for p in DECLARATION["providers"] for x in p["support"]}
        self.assertEqual(actual, {"finance.order-consequence.process": "PARTIAL",
                                  "inventory.availability.query": "IMPLEMENTED"})
        self.assertTrue((F1 | F2 | F3 | PEOPLE | WMS).isdisjoint(actual))

    def test_canonical_f1_and_people_are_planned_not_registered_as_providers(self):
        plans = {x.get("capability_key", x.get("proposed_key")): x for x in DECLARATION["planned_capabilities"]}
        self.assertEqual(set(plans), F1 | F2 | F3 | PEOPLE | WMS)
        for key in F1 | PEOPLE:
            self.assertEqual(plans[key]["proposal_status"], "CONTRACTED")
            self.assertEqual(plans[key]["capability_key"], key)

    def test_f2_f3_census_and_wms_stay_nonrunnable(self):
        plans = {x.get("capability_key", x.get("proposed_key")): x for x in DECLARATION["planned_capabilities"]}
        for key in F2 | F3:
            self.assertEqual(plans[key]["proposal_status"], "PROPOSED")
            self.assertEqual(plans[key]["proposed_key"], key)
        for key in WMS:
            self.assertEqual(plans[key]["proposal_status"], "CONTRACTING")
            self.assertNotIn("target_provider_key", plans[key], "WMS technology was not selected")

    def test_no_cross_domain_finance_overlap_or_native_placement_authority(self):
        all_keys = F1 | F2 | F3 | PEOPLE | WMS
        self.assertNotIn("finance.intercompany.reconcile", all_keys)
        self.assertNotIn("finance.ledger.balance.read", all_keys)
        self.assertTrue(all(key.count(".") == 2 for key in all_keys))
        for p in DECLARATION["providers"]:
            for entry in p["support"]:
                self.assertNotIn("certified", entry)
                self.assertNotIn("binding", entry)


if __name__ == "__main__":
    unittest.main()
