"""Non-activating payroll metadata proposal: no payroll approval, GL or payment."""
from typing import Protocol

from .model import PayrollDraft, PayrollPolicyError


class PayrollProposalAuthority(Protocol):
    def authorize(
        self, *, proof: str, operation: str, tenant_id: str,
        legal_employer_id: str, run_ref: str,
    ) -> str:
        """Current IAM/CP run-scoped maker attestation; must fail closed."""


class PayrollDraftRepository(Protocol):
    def latest(self, *, tenant_id: str, employer_id: str, run_ref: str) -> PayrollDraft | None: ...

    def append_if_version(self, draft: PayrollDraft, *, previous_version: int | None) -> None:
        """Transactional CAS; historical rows are never changed."""


class PayrollDraftService:
    def __init__(self, authority: PayrollProposalAuthority, repository: PayrollDraftRepository):
        self.authority, self.repository = authority, repository

    def propose(self, draft: PayrollDraft, *, authority_proof: str) -> None:
        if not isinstance(authority_proof, str) or not authority_proof:
            raise PayrollPolicyError("Independent payroll maker authority required")
        principal = self.authority.authorize(
            proof=authority_proof, operation="payroll.run.propose",
            tenant_id=draft.tenant_id, legal_employer_id=draft.legal_employer_id,
            run_ref=draft.run_ref,
        )
        if not isinstance(principal, str) or principal != draft.maker_ref:
            raise PayrollPolicyError("Payroll maker identity does not match authority")
        previous = self.repository.latest(
            tenant_id=draft.tenant_id, employer_id=draft.legal_employer_id,
            run_ref=draft.run_ref,
        )
        if previous:
            if (draft.version != previous.version + 1
                or (draft.period_from, draft.period_until, draft.statutory_jurisdiction,
                    draft.currency, draft.correction_of_run_ref)
                    != (previous.period_from, previous.period_until,
                        previous.statutory_jurisdiction, previous.currency,
                        previous.correction_of_run_ref)):
                raise PayrollPolicyError("Payroll draft cannot change period or scope")
        elif draft.version != 1:
            raise PayrollPolicyError("First payroll draft version must be one")
        self.repository.append_if_version(
            draft, previous_version=previous.version if previous else None,
        )
