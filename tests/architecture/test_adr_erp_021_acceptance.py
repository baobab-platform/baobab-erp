"""ADR-ERP-021 acceptance guard.

Architectural acceptance is normative for future ERP/CP/ZuriBeans design;
it never fabricates incorporation, CP authority, a production client or
financial certification. These source-only checks cannot qualify runtime.
"""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/adr/ADR-ERP-021 — ZuriBeans Multi-Market AD_Client Topology.md"


class ZuriBeansTopologyDecisionTests(unittest.TestCase):
    def test_decision_is_accepted_but_incorporation_remains_unverified(self):
        text = ADR.read_text()
        self.assertIn("**Status:** Accepted", text)
        self.assertIn("8 November 2026", text)
        self.assertIn("incorporation", text.lower())
        self.assertIn("in progress", text.lower())
        self.assertIn("not evidence", text.lower())
        self.assertIn("ZURIBEANS_UG", text)
        self.assertIn("ZURIBEANS_ZA", text)
        self.assertIn("ERP-AF-SOUTH-01", text)
        # A neighbouring group company is not ZuriBeans: SA incorporation is
        # independently recorded; Uganda Thamani incorporation remains pending.
        self.assertIn("Nabhold Group Africa and Thamani Global are **legally incorporated in South", text)
        self.assertIn("Uganda incorporation remains pending", text)
        self.assertIn("ZuriBeans' own in-progress", text)
        for index in range(1, 9):
            self.assertIn(f"INV-ERP-TOPO-{index:03d}", text)

    def test_the_two_production_documents_remain_blocked_and_independent(self):
        templates = {}
        for suffix, country, currency in (
            ("ug", "UG", "UGX"),
            ("za", "ZA", "ZAR"),
        ):
            path = ROOT / f"config/provisioning/zuribeans-{suffix}.production.template.json"
            data = json.loads(path.read_text())
            templates[suffix] = data
            self.assertEqual("draft-not-approved", data["status"])
            self.assertEqual("production", data["target_environment"])
            self.assertEqual(country, data["jurisdiction_code"])
            self.assertEqual(currency, data["accounting"]["functional_currency"])
            self.assertEqual([country], [m["country_code"] for m in data["markets"]])
            self.assertTrue(data["registration_identifier"].startswith("REQUIRED_"))
            self.assertTrue(data["legal_entity_id"].startswith("REQUIRED_CP_"))
            self.assertTrue(data["accounting"]["approved_by"].startswith("REQUIRED_"))
            self.assertTrue(data["accounting"]["tax_profile"].startswith("REQUIRED_"))
        self.assertNotEqual(templates["ug"]["legal_entity_id"], templates["za"]["legal_entity_id"])
        self.assertNotEqual(templates["ug"]["provisioning_id"], templates["za"]["provisioning_id"])
        self.assertEqual(templates["ug"]["tenant_id"], templates["za"]["tenant_id"])
        self.assertEqual(templates["ug"]["engine_instance_id"], templates["za"]["engine_instance_id"])

    def test_conformance_tracks_acceptance_separately_from_implementation(self):
        conformance = (ROOT / "architecture/conformance.yaml").read_text()
        block = conformance.split("  - id: ADR-ERP-021\n", 1)[1].split("\n  - id:", 1)[0]
        self.assertIn("status: partial", block)
        self.assertIn("ADR decision ACCEPTED", block)
        self.assertIn("incorporation is still in progress", block)
        self.assertIn("draft-not-approved", block)
        self.assertIn("EA-09", block)
        self.assertIn("tests/architecture/test_adr_erp_021_acceptance.py", block)

    def test_decision_is_indexed_without_changing_people_decision(self):
        index = (ROOT / "docs/adr/README.md").read_text()
        self.assertIn("ADR-ERP-021: ZuriBeans multi-market", index)
        self.assertIn("ADR-ERP-023: Baobab People", index)
        people = (ROOT / "docs/adr/ADR-ERP-023 — Baobab People African Workforce, Payroll, CDSoftware Re-engineering and PostgreSQL 17.md").read_text()
        self.assertIn("**Status:** Accepted", people)


if __name__ == "__main__":
    unittest.main()
