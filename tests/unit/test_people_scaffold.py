"""Baobab People BP-00 tests: source-only/port qualification, not live iDempiere."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from people.workforce import EmploymentVersion, PeopleDomainError, WorkforceService
from people.payroll import PayrollDraft, VerifiedCalculation, PayrollPolicyError, PayrollEligibilityGate


class Authority:
    def authorize(self, *, proof, operation, tenant_id, legal_employer_id):
        if proof != "attested-employer" or tenant_id != "tn_alpha" or legal_employer_id != "le_alpha":
            raise PeopleDomainError("Employer authority denied")
        return "principal_hr_1"

    def attest_approver(self, *, proof, tenant_id, legal_employer_id, run_ref):
        if (proof, tenant_id, legal_employer_id) != ("attested-checker", "tn_alpha", "le_alpha"):
            raise PayrollPolicyError("Checker authority denied")
        return "principal_payroll_checker"


class Store:
    def __init__(self):
        self.values = {}

    def latest(self, *, tenant_id, employer_id, person_ref):
        return self.values.get((tenant_id, employer_id, person_ref))

    def append_if_version(self, record, *, previous_version, principal_ref):
        if not principal_ref:
            raise PeopleDomainError('Attested writer required')
        key = (record.tenant_id, record.legal_employer_id, record.person_ref)
        existing = self.values.get(key)
        if (existing.version if existing else None) != previous_version:
            raise PeopleDomainError("Concurrent employment version change")
        self.values[key] = record


NOW = datetime(2026, 11, 7, 8, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64
# An opaque synthetic reference, deliberately not a token or API secret.
EVIDENCE_REF = "ev_" + "qualified_" + "1"


class Verifier:
    def __init__(self, receipt): self.receipt = receipt
    def verify(self, *, evidence_ref, tenant_id, employer_id, run_ref, version):
        if evidence_ref != EVIDENCE_REF:
            raise PayrollPolicyError("Evidence not registered")
        return self.receipt


def workforce_record(**changes):
    return replace(EmploymentVersion(
        tenant_id="tn_alpha", legal_employer_id="le_alpha", person_ref="person_opaque_1",
        version=1, effective_from=date(2026, 11, 1), effective_until=None,
        work_jurisdiction="ZA", tax_jurisdiction="ZA", pay_currency="ZAR",
        contract_evidence_ref="doc_pinned_1",
    ), **changes)


def payroll_draft(**changes):
    return replace(PayrollDraft(
        run_ref="payrun_2026_11", version=1, tenant_id="tn_alpha",
        legal_employer_id="le_alpha", maker_ref="principal_payroll_maker",
        period_from=date(2026, 11, 1), period_until=date(2026, 11, 30),
        statutory_jurisdiction="ZA", currency="ZAR", rule_pack_sha256=DIGEST,
    ), **changes)


def calculation_receipt(**changes):
    return replace(VerifiedCalculation(
        run_ref="payrun_2026_11", version=1, tenant_id="tn_alpha",
        legal_employer_id="le_alpha", statutory_jurisdiction="ZA", currency="ZAR",
        rule_pack_sha256=DIGEST, expires_at=NOW + timedelta(minutes=5),
        independently_qualified=True, complete=True, evidence_reference=EVIDENCE_REF,
    ), **changes)


class WorkforceTests(unittest.TestCase):
    def test_versions_are_employer_scoped_and_monotone(self):
        store = Store()
        service = WorkforceService(Authority(), store)
        first = workforce_record()
        service.propose(first, authority_proof="attested-employer")
        service.propose(workforce_record(version=2, effective_from=date(2026, 12, 1)), authority_proof="attested-employer")
        self.assertEqual(store.latest(tenant_id="tn_alpha", employer_id="le_alpha", person_ref=first.person_ref).version, 2)

    def test_foreign_employer_and_missing_authority_denied(self):
        store = Store()
        service = WorkforceService(Authority(), store)
        for record, proof in ((workforce_record(legal_employer_id="le_other"), "attested-employer"), (workforce_record(), "")):
            with self.subTest(record=record.legal_employer_id, proof=proof), self.assertRaises(PeopleDomainError):
                service.propose(record, authority_proof=proof)
        self.assertFalse(store.values)

    def test_invalid_versions_and_effective_window_denied(self):
        for changes in (
            {"version": True}, {"correction_of_run_ref": ""},
            {"run_ref": "bad run with spaces"},
            {"period_from": datetime(2026, 11, 1, tzinfo=timezone.utc)}, {"version": 0},
            {"effective_until": date(2026, 11, 1)},
            {"tax_jurisdiction": "za"}, {"pay_currency": "zar"},
            {"state": "ACTIVE"}, {"contract_evidence_ref": "bad evidence ref"},
            {"person_ref": "person@untrusted"}, {"tenant_id": "tn/unsafe"},
            {"effective_from": datetime(2026, 11, 1, tzinfo=timezone.utc)},
        ):
            with self.subTest(changes=changes), self.assertRaises(PeopleDomainError):
                workforce_record(**changes)

    def test_stale_and_overlapping_proposals_refused(self):
        store = Store()
        svc = WorkforceService(Authority(), store)
        svc.propose(workforce_record(), authority_proof="attested-employer")
        for changes in (
            {"version": 1, "effective_from": date(2026, 12, 1)},
            {"version": 2, "effective_from": date(2026, 10, 1)},
        ):
            with self.subTest(changes=changes), self.assertRaises(PeopleDomainError):
                svc.propose(workforce_record(**changes), authority_proof="attested-employer")
        with self.assertRaises(PeopleDomainError):
            store.append_if_version(workforce_record(version=2, effective_from=date(2026, 12, 1)), previous_version=None)


class PayrollGateTests(unittest.TestCase):
    def test_fresh_qualified_receipt_and_independent_checker_are_eligible_only(self):
        evidence = PayrollEligibilityGate(Authority(), Verifier(calculation_receipt())).check(
            payroll_draft(), authority_proof="attested-checker",
            calculation_evidence_ref=EVIDENCE_REF, now=NOW)
        self.assertEqual(evidence.checker_ref, "principal_payroll_checker")
        self.assertFalse(hasattr(evidence, "payment_authorisation"))
        self.assertFalse(hasattr(evidence, "journal_posted"))

    def test_self_approval_and_invalid_authority_refused(self):
        draft = payroll_draft(maker_ref="principal_payroll_checker")
        for d, token in ((draft, "attested-checker"), (payroll_draft(), "wrong")):
            with self.subTest(token=token, maker=d.maker_ref), self.assertRaises(PayrollPolicyError):
                PayrollEligibilityGate(Authority(), Verifier(calculation_receipt())).check(
                    d, authority_proof=token, calculation_evidence_ref=EVIDENCE_REF, now=NOW)

    def test_evidence_scope_staleness_qualification_and_completion_fail_closed(self):
        receipts = (
            calculation_receipt(tenant_id="tn_elsewhere"),
            calculation_receipt(legal_employer_id="le_other"),
            calculation_receipt(version=2),
            calculation_receipt(currency="UGX"),
            calculation_receipt(rule_pack_sha256="b" * 64),
            calculation_receipt(independently_qualified=False),
            calculation_receipt(complete=False),
            calculation_receipt(expires_at=NOW),
            calculation_receipt(evidence_reference="ev_different"),
        )
        for receipt in receipts:
            with self.subTest(receipt=receipt), self.assertRaises(PayrollPolicyError):
                PayrollEligibilityGate(Authority(), Verifier(receipt)).check(
                    payroll_draft(), authority_proof="attested-checker",
                    calculation_evidence_ref=EVIDENCE_REF, now=NOW)

    def test_invalid_period_pack_and_correction_denied(self):
        for changes in (
            {"period_until": date(2026, 10, 31)},
            {"rule_pack_sha256": "unknown"},
            {"statutory_jurisdiction": "ZAF"},
            {"correction_of_run_ref": "payrun_2026_11"},
            {"version": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(PayrollPolicyError):
                payroll_draft(**changes)


if __name__ == "__main__":
    unittest.main()
