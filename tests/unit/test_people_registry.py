"""BP-04 authority and revision gates; no payroll calculation, GL or bank release."""
from dataclasses import replace
from datetime import date
import unittest

from people.payroll import PayrollDraft, PayrollDraftService, PayrollPolicyError
from people.workforce import EmploymentVersion, WorkforceService, PeopleDomainError

class Authority:
    def authorize(self, *, proof, operation, tenant_id, legal_employer_id, run_ref=None):
        if proof != "attested" or (tenant_id, legal_employer_id) != ("tn_demo", "LE-DEMO"):
            raise PayrollPolicyError("CP employer authority denied")
        return "maker_001" if operation == "payroll.run.propose" else "hr_001"

class Store:
    def __init__(self): self.rows = {}
    def latest(self, *, tenant_id, employer_id, run_ref):
        return self.rows.get((tenant_id, employer_id, run_ref))
    def append_if_version(self, draft, *, previous_version):
        key = (draft.tenant_id, draft.legal_employer_id, draft.run_ref)
        previous = self.rows.get(key)
        if (previous.version if previous else None) != previous_version:
            raise PayrollPolicyError("Concurrent version change")
        self.rows[key] = draft

def draft(**kw):
    return replace(PayrollDraft(
        run_ref="run_demo", version=1, tenant_id="tn_demo", legal_employer_id="LE-DEMO",
        maker_ref="maker_001", period_from=date(2026, 11, 1),
        period_until=date(2026, 11, 30), statutory_jurisdiction="ZA",
        currency="ZAR", rule_pack_sha256="a" * 64,
    ), **kw)

class DraftPolicyTests(unittest.TestCase):
    def test_employer_maker_gate_and_stale_revision(self):
        store = Store()
        svc = PayrollDraftService(Authority(), store)
        svc.propose(draft(), authority_proof="attested")
        svc.propose(draft(version=2, rule_pack_sha256="b" * 64), authority_proof="attested")
        self.assertEqual(store.latest(tenant_id="tn_demo", employer_id="LE-DEMO", run_ref="run_demo").version, 2)
        for candidate, proof in (
            (draft(version=3, maker_ref="maker_other"), "attested"),
            (draft(version=3, legal_employer_id="LE-OTHER"), "attested"),
            (draft(version=3, period_from=date(2026, 10, 1)), "attested"),
            (draft(version=3), ""),
            (draft(version=2), "attested"),
        ):
            with self.subTest(candidate=candidate, proof=proof), self.assertRaises(PayrollPolicyError):
                svc.propose(candidate, authority_proof=proof)
        self.assertFalse(hasattr(svc, "approve"))
        self.assertFalse(hasattr(svc, "post_journal"))
        self.assertFalse(hasattr(svc, "release_bank_payment"))

if __name__ == "__main__":
    unittest.main()
