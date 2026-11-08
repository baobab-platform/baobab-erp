"""BP-04 disposable PostgreSQL 17 evidence; no payroll activation or real PII.

CI opts in explicitly. Local/persistent databases do not execute this test:
append-only proposals are intentionally not deleted by a test cleanup path.
"""
import os
import uuid
import unittest
from dataclasses import replace
from datetime import date

import psycopg

from _postgres import require_database_url
from people.workforce import EmploymentVersion, PeopleDomainError, WorkforceService
from people.workforce.postgres_store import PostgresEmploymentProposalStore
from people.payroll import PayrollDraft, PayrollPolicyError, PayrollDraftService
from people.payroll.postgres_store import PostgresPayrollDraftStore

class Authority:
    def authorize(self, *, proof, operation, tenant_id, legal_employer_id, run_ref=None):
        if proof != "synthetic-cp-allow" or not tenant_id.startswith("tn_") or legal_employer_id != "LE-PEOPLE-TEST":
            raise PeopleDomainError("Synthetic authority denied")
        if operation == "payroll.run.propose":
            return "principal_maker_001"
        if operation == "workforce.employment.propose":
            return "principal_hr_001"
        raise PeopleDomainError("Unknown operation")

class PeoplePostgresTests(unittest.TestCase):
    def setUp(self):
        if os.getenv("BAOBAB_PEOPLE_EXPERIMENTAL") != "1" or os.getenv("BAOBAB_PEOPLE_TEST_DISPOSABLE") != "1":
            self.skipTest("BP-04 runs only against an expressly disposable PostgreSQL 17 CI database")
        self.conn = psycopg.connect(require_database_url())
        self.addCleanup(self.conn.close)
        self.tenant = "tn_" + uuid.uuid4().hex[:16]
        self.employer = "LE-PEOPLE-TEST"
        self.person = "person_opaque_" + uuid.uuid4().hex[:12]
        self.run_ref = "run_" + uuid.uuid4().hex[:16]
        with self.conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            self.assertTrue(cur.fetchone()[0].startswith("17"))
            cur.execute("SELECT to_regclass('baobab_people.employment_proposal'), "
                        "to_regclass('baobab_people.payroll_draft')")
            a, b = cur.fetchone()
            self.assertIsNotNone(a)
            self.assertIsNotNone(b)
        self.conn.commit()

    def employment(self, **changes):
        return replace(EmploymentVersion(
            tenant_id=self.tenant, legal_employer_id=self.employer,
            person_ref=self.person, version=1, effective_from=date(2026, 11, 1),
            effective_until=None, work_jurisdiction="ZA", tax_jurisdiction="ZA",
            pay_currency="ZAR", contract_evidence_ref="ev_synthetic_contract_01",
        ), **changes)

    def draft(self, **changes):
        return replace(PayrollDraft(
            run_ref=self.run_ref, version=1, tenant_id=self.tenant,
            legal_employer_id=self.employer, maker_ref="principal_maker_001",
            period_from=date(2026, 11, 1), period_until=date(2026, 11, 30),
            statutory_jurisdiction="ZA", currency="ZAR",
            rule_pack_sha256="a" * 64,
        ), **changes)

    def refusal(self, query, args=()):
        with self.conn.cursor() as cur:
            cur.execute("SAVEPOINT people_negative_case")
            with self.assertRaises(psycopg.Error) as result:
                cur.execute(query, args)
            self.assertIn("BAOBAB_PEOPLE_DENIED", str(result.exception))
            cur.execute("ROLLBACK TO SAVEPOINT people_negative_case")
            cur.execute("RELEASE SAVEPOINT people_negative_case")

    def test_employment_persisted_original_immutable_and_employer_scoped(self):
        store = PostgresEmploymentProposalStore(self.conn)
        service = WorkforceService(Authority(), store)
        first = self.employment()
        service.propose(first, authority_proof="synthetic-cp-allow")
        self.conn.commit()
        with psycopg.connect(require_database_url()) as independent:
            readback = PostgresEmploymentProposalStore(independent)
            self.assertEqual(first, readback.latest(
                tenant_id=self.tenant, employer_id=self.employer, person_ref=self.person))
            self.assertIsNone(readback.latest(
                tenant_id="tn_other", employer_id=self.employer, person_ref=self.person))
            self.assertIsNone(readback.latest(
                tenant_id=self.tenant, employer_id="LE-OTHER", person_ref=self.person))
        with self.conn.cursor() as cur:
            cur.execute("""SELECT writer_principal_ref, state, version
                              FROM baobab_people.employment_proposal
                             WHERE tenant_id=%s AND legal_employer_id=%s
                               AND person_ref=%s""", (self.tenant, self.employer, self.person))
            self.assertEqual(cur.fetchone(), ("principal_hr_001", "PROPOSED", 1))
        self.refusal("""UPDATE baobab_people.employment_proposal SET state='ACTIVE'
                          WHERE tenant_id=%s AND legal_employer_id=%s""",
                     (self.tenant, self.employer))
        self.refusal("""DELETE FROM baobab_people.employment_proposal
                          WHERE tenant_id=%s AND legal_employer_id=%s""",
                     (self.tenant, self.employer))
        self.refusal("TRUNCATE baobab_people.employment_proposal")
        second = self.employment(version=2, effective_from=date(2027, 1, 1))
        service.propose(second, authority_proof="synthetic-cp-allow")
        self.assertEqual(store.latest(
            tenant_id=self.tenant, employer_id=self.employer, person_ref=self.person).version, 2)
        with self.assertRaises(PeopleDomainError):
            service.propose(self.employment(version=2), authority_proof="synthetic-cp-allow")
        self.conn.rollback()

    def test_direct_sql_cas_and_scope_and_explicit_end_are_enforced(self):
        with self.conn.cursor() as cur:
            # Source SQL alone is never IAM/CP authorization; this is a
            # database anti-corruption proof, not evidence of legal authority.
            cur.execute("""INSERT INTO baobab_people.employment_proposal
                 (tenant_id,legal_employer_id,person_ref,version,effective_from,
                  effective_until,work_jurisdiction,tax_jurisdiction,pay_currency,
                  contract_evidence_ref,writer_principal_ref)
                  VALUES (%s,%s,%s,1,'2026-11-01','2026-12-01','ZA','ZA','ZAR',
                          'ev_synthetic_001','principal_hr_001')""",
                        (self.tenant, self.employer, self.person))
        self.refusal("""INSERT INTO baobab_people.employment_proposal
                 (tenant_id,legal_employer_id,person_ref,version,effective_from,
                  work_jurisdiction,tax_jurisdiction,pay_currency,
                  contract_evidence_ref,writer_principal_ref)
                 VALUES (%s,%s,%s,3,'2026-11-20','ZA','ZA','ZAR',
                         'ev_synthetic_002','principal_hr_001')""",
                     (self.tenant, self.employer, self.person))
        self.refusal("""INSERT INTO baobab_people.employment_proposal
                 (tenant_id,legal_employer_id,person_ref,version,effective_from,
                  work_jurisdiction,tax_jurisdiction,pay_currency,
                  contract_evidence_ref,writer_principal_ref)
                 VALUES (%s,%s,%s,2,'2026-11-20','ZA','ZA','ZAR',
                         'ev_synthetic_002','principal_hr_001')""",
                     (self.tenant, self.employer, self.person))
        self.conn.rollback()

    def test_payroll_draft_versions_corrections_and_absence_of_payment_authority(self):
        store = PostgresPayrollDraftStore(self.conn)
        service = PayrollDraftService(Authority(), store)
        original = self.draft()
        service.propose(original, authority_proof="synthetic-cp-allow")
        self.conn.commit()
        with psycopg.connect(require_database_url()) as independent:
            self.assertEqual(original, PostgresPayrollDraftStore(independent).latest(
                tenant_id=self.tenant, employer_id=self.employer, run_ref=self.run_ref))
            self.assertIsNone(PostgresPayrollDraftStore(independent).latest(
                tenant_id=self.tenant, employer_id="LE-OTHER", run_ref=self.run_ref))
        second = self.draft(version=2, rule_pack_sha256="b" * 64)
        service.propose(second, authority_proof="synthetic-cp-allow")
        self.assertEqual(store.latest(tenant_id=self.tenant, employer_id=self.employer,
                                      run_ref=self.run_ref).version, 2)
        with self.assertRaises(PayrollPolicyError):
            service.propose(self.draft(version=3, period_until=date(2026, 12, 1)),
                            authority_proof="synthetic-cp-allow")
        with self.assertRaises(PayrollPolicyError):
            service.propose(self.draft(version=3, maker_ref="principal_other"),
                            authority_proof="synthetic-cp-allow")
        with self.conn.cursor() as cur:
            cur.execute("""SELECT state, count(*) FROM baobab_people.payroll_draft
                            WHERE tenant_id=%s AND legal_employer_id=%s
                            GROUP BY state""", (self.tenant, self.employer))
            self.assertEqual(cur.fetchone(), ("DRAFT", 2))
        self.refusal("""UPDATE baobab_people.payroll_draft SET state='APPROVED'
                        WHERE tenant_id=%s""", (self.tenant,))
        self.refusal("TRUNCATE baobab_people.payroll_draft")
        self.conn.rollback()

    def test_correction_cannot_cross_employer_or_reference_unseen_run(self):
        store = PostgresPayrollDraftStore(self.conn)
        service = PayrollDraftService(Authority(), store)
        correction = self.draft(run_ref="correction_" + uuid.uuid4().hex[:8],
                                correction_of_run_ref=self.run_ref)
        with self.assertRaises(psycopg.Error) as err:
            service.propose(correction, authority_proof="synthetic-cp-allow")
        self.assertIn("BAOBAB_PEOPLE_DENIED", str(err.exception))
        self.conn.rollback()
        service.propose(self.draft(), authority_proof="synthetic-cp-allow")
        service.propose(correction, authority_proof="synthetic-cp-allow")
        self.assertIsNotNone(store.latest(tenant_id=self.tenant, employer_id=self.employer,
                                          run_ref=correction.run_ref))
        self.conn.rollback()

if __name__ == "__main__":
    unittest.main()
