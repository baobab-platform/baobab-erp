"""Source-only wiring test; independent real CP/PG17/ERP evidence is CI-only."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "idempiere/acceptance/erp-a/driver"))

from people_dev_connected import seed_choice  # noqa: E402


class DisposableComposeRecorder:
    def __init__(self):
        self.commands = []

    def scalar(self, service, user, database, sql):
        self.commands.append(("scalar", sql))
        if "SELECT status FROM capability.capability" in sql:
            return "DRAFT"
        if "SELECT capability_id::text FROM capability.capability" in sql:
            return "22222222-2222-4222-8222-222222222222"
        if "SELECT count(*) FROM capability.people_provider_choice" in sql:
            return "1"
        raise AssertionError("unreviewed SQL readback")

    def sql(self, service, user, database, statement):
        self.commands.append(("sql", statement))
        return []


class PeopleConnectedSourceWiringTest(unittest.TestCase):
    def test_disposable_choice_sql_is_complete_and_never_claims_statute(self):
        c = DisposableComposeRecorder()
        state = {"second": {
            "tenant": "tn_disposable",
            "legal_entity": "TEST-EMPLOYER",
            "maker": "11111111-1111-4111-8111-111111111111",
            "checker": "33333333-3333-4333-8333-333333333333",
        }}
        fixture = seed_choice(c, state)
        statements = [sql for kind, sql in c.commands if kind == "sql"]
        self.assertEqual(len(statements), 1)
        script = statements[0]
        for marker in (
            "BEGIN;", "COMMIT;", "capability.people_provider_choice",
            "provider_capability_certification", "capability.capability_grant",
            "'EXTERNAL','ACTIVE'", "NOT statutory or real provider certification",
            """'[{"dev_only":true}]'::jsonb""",
        ):
            self.assertIn(marker, script)
        self.assertEqual(fixture["tenant"], "tn_disposable")
        self.assertEqual(fixture["employer"], "TEST-EMPLOYER")
        self.assertIn("UPDATE capability.capability SET status='ACTIVE'", script)
        self.assertNotIn("baobab_people.payroll_draft", script)

    def test_self_approval_cannot_seed_a_choice(self):
        c = DisposableComposeRecorder()
        state = {"second": {
            "tenant": "tn_disposable", "legal_entity": "TEST-EMPLOYER",
            "maker": "11111111-1111-4111-8111-111111111111",
            "checker": "11111111-1111-4111-8111-111111111111",
        }}
        with self.assertRaisesRegex(RuntimeError, "SELF_APPROVAL"):
            seed_choice(c, state)
        self.assertEqual(c.commands, [])


if __name__ == "__main__":
    unittest.main()
