"""Readiness-only gate; a positive result is not payroll approval or payment authority."""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from .model import PayrollDraft, PayrollPolicyError, VerifiedCalculation


class PayrollApprovalAuthority(Protocol):
    def attest_approver(
        self, *, proof: str, tenant_id: str, legal_employer_id: str, run_ref: str
    ) -> str:
        """Resolve current IAM + CP run-scoped maker/checker authority or raise."""


class CalculationVerifier(Protocol):
    def verify(
        self, *, evidence_ref: str, tenant_id: str, employer_id: str, run_ref: str, version: int
    ) -> VerifiedCalculation:
        """Verify a qualified provider's signed result; never trust user-provided flags."""


@dataclass(frozen=True, slots=True)
class ApprovalEligibility:
    run_ref: str
    version: int
    checker_ref: str
    evidence_reference: str
    # Not an approval: no persistent transition, GL posting or bank authority.


class PayrollEligibilityGate:
    def __init__(self, authority: PayrollApprovalAuthority, verifier: CalculationVerifier):
        self.authority, self.verifier = authority, verifier

    def check(
        self, draft: PayrollDraft, *, authority_proof: str, calculation_evidence_ref: str,
        now: datetime,
    ) -> ApprovalEligibility:
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise PayrollPolicyError("Timezone-aware verification time required")
        if not authority_proof or not calculation_evidence_ref:
            raise PayrollPolicyError("Independent authority and calculation evidence required")
        checker = self.authority.attest_approver(
            proof=authority_proof, tenant_id=draft.tenant_id,
            legal_employer_id=draft.legal_employer_id, run_ref=draft.run_ref,
        )
        if not isinstance(checker, str) or not checker.strip() or checker != checker.strip() or checker == draft.maker_ref:
            raise PayrollPolicyError("Independent payroll checker required")
        receipt = self.verifier.verify(
            evidence_ref=calculation_evidence_ref, tenant_id=draft.tenant_id,
            employer_id=draft.legal_employer_id, run_ref=draft.run_ref, version=draft.version,
        )
        if not isinstance(receipt, VerifiedCalculation) or not receipt.matches(draft, now=now):
            raise PayrollPolicyError("Current qualified complete payroll evidence required")
        if receipt.evidence_reference != calculation_evidence_ref:
            raise PayrollPolicyError("Payroll evidence reference mismatch")
        return ApprovalEligibility(draft.run_ref, draft.version, checker, receipt.evidence_reference)
