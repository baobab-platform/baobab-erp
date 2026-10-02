import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg

from provisioning.finance_baseline_store import FinanceBaselineError, PostgresFinanceBaselineStore

from _postgres import connect

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


class FinanceBaselineStoreTests(unittest.TestCase):
    """The table is append-only, so nothing here commits: every test rolls back and leaves no row behind."""

    def setUp(self):
        self.connection = connect()
        self.addCleanup(self._rollback)
        self.entity = f"TEST-{uuid.uuid4().hex[:12].upper()}"
        self.store = PostgresFinanceBaselineStore(self.connection)

    def _rollback(self):
        self.connection.rollback()
        self.connection.close()

    def record(self, **overrides):
        values = dict(
            legal_entity_id=self.entity, functional_currency="ZAR", fiscal_year_start_month=1,
            chart_of_accounts_template="coa-zb-v1", accounting_schema="ZB Primary", tax_profile="tax-za-v1",
            costing_method="average-po", effective_from=date(2026, 10, 1), approved_by="Thandi Nkosi",
            approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc), evidence_reference="FIN-CHG-2026-114", now=NOW)
        values.update(overrides)
        return self.store.record(**values)

    def test_versions_are_dense_per_legal_entity_and_history_is_kept(self):
        first, second = self.record(), self.record(tax_profile="tax-za-v2", effective_from=date(2026, 11, 1))
        self.assertEqual((first.version, second.version), (1, 2))
        other = self.record(legal_entity_id=self.entity + "-B")
        self.assertEqual(other.version, 1)
        self.assertEqual([b.version for b in self.store.history(self.entity)], [1, 2])

    def test_the_baseline_in_force_on_a_date_is_the_latest_effective_not_after_it(self):
        self.record()
        self.record(tax_profile="tax-za-v2", effective_from=date(2026, 11, 1))
        self.assertIsNone(self.store.effective(self.entity, date(2026, 9, 30)), "not yet in force")
        self.assertEqual(self.store.effective(self.entity, date(2026, 10, 15)).tax_profile, "tax-za-v1")
        self.assertEqual(self.store.effective(self.entity, date(2026, 11, 1)).tax_profile, "tax-za-v2")

    def test_the_latest_version_wins_among_equal_effective_dates(self):
        self.record()
        self.record(costing_method="fifo")
        self.assertEqual(self.store.effective(self.entity, date(2026, 10, 1)).costing_method, "fifo")

    def test_an_unknown_legal_entity_has_no_baseline_and_nothing_is_defaulted(self):
        self.assertIsNone(self.store.effective(self.entity, date(2030, 1, 1)))

    def test_an_approver_must_be_a_named_person(self):
        for approver in ("system", " SYSTEM ", "Bootstrap", "automation", "", "  ", "REQUIRED_FINANCE_APPROVER", "n/a"):
            with self.subTest(approver):
                with self.assertRaises(FinanceBaselineError):
                    self.record(approved_by=approver)
        self.assertEqual(self.store.history(self.entity), [])

    def test_evidence_is_required(self):
        for evidence in ("", "   ", "REQUIRED_EVIDENCE"):
            with self.subTest(evidence):
                with self.assertRaises(FinanceBaselineError):
                    self.record(evidence_reference=evidence)

    def test_placeholders_are_refused_in_every_accounting_field(self):
        for field in ("chart_of_accounts_template", "accounting_schema", "tax_profile", "costing_method", "functional_currency"):
            with self.subTest(field):
                with self.assertRaises(FinanceBaselineError):
                    self.record(**{field: "REQUIRED_VERSIONED_VALUE"})

    def test_an_approval_cannot_be_in_the_future_or_lack_a_time_zone(self):
        with self.assertRaises(FinanceBaselineError):
            self.record(approved_at=NOW + timedelta(days=1))
        with self.assertRaises(FinanceBaselineError):
            self.record(approved_at=datetime(2026, 9, 1))

    def test_the_database_enforces_the_same_rules_independently_of_this_code(self):
        self.record()
        insert = ("INSERT INTO baobab.financial_configuration_baseline (legal_entity_id, version, functional_currency, "
                  "fiscal_year_start_month, chart_of_accounts_template, accounting_schema, tax_profile, costing_method, "
                  "effective_from, approved_by, approved_at, evidence_reference) "
                  "VALUES (%s, 2, %s, %s, 'coa', 'schema', 'tax', 'fifo', '2026-10-01', %s, now(), %s)")
        for args in ((self.entity, "ZAR", 1, "system", "ev"), (self.entity, "ZAR", 1, "  ", "ev"),
                     (self.entity, "ZAR", 1, "Thandi Nkosi", ""), (self.entity, "zar", 1, "Thandi Nkosi", "ev"),
                     (self.entity, "ZAR", 13, "Thandi Nkosi", "ev")):
            with self.subTest(args):
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with self.connection.transaction():
                        self.connection.execute(insert, args)

    def test_a_recorded_baseline_cannot_be_changed_or_deleted(self):
        self.record()
        for statement in (
                "UPDATE baobab.financial_configuration_baseline SET tax_profile = 'other' WHERE legal_entity_id = %s",
                "DELETE FROM baobab.financial_configuration_baseline WHERE legal_entity_id = %s"):
            with self.subTest(statement):
                with self.assertRaises(psycopg.errors.RestrictViolation):
                    with self.connection.transaction():
                        self.connection.execute(statement, (self.entity,))
        self.assertEqual(len(self.store.history(self.entity)), 1)


if __name__ == "__main__":
    unittest.main()
