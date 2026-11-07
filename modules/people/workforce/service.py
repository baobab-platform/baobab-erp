"""Employer-scoped version proposal. Trust and atomic persistence are explicit ports."""
from typing import Protocol
from .model import EmploymentVersion, PeopleDomainError


class WorkforceAuthority(Protocol):
    def authorize(
        self, *, proof: str, operation: str, tenant_id: str, legal_employer_id: str
    ) -> str:
        """Verify current IAM/CP authority and return attested principal reference, else raise."""


class EmploymentRepository(Protocol):
    def latest(self, *, tenant_id: str, employer_id: str, person_ref: str) -> EmploymentVersion | None: ...
    def append_if_version(self, record: EmploymentVersion, *, previous_version: int | None) -> None:
        """Atomically compare expected version and append; NEVER update historical versions."""


class WorkforceService:
    def __init__(self, authority: WorkforceAuthority, repository: EmploymentRepository):
        self.authority, self.repository = authority, repository

    def propose(self, record: EmploymentVersion, *, authority_proof: str) -> None:
        if not authority_proof:
            raise PeopleDomainError("Employer authority proof required")
        principal = self.authority.authorize(
            proof=authority_proof, operation="workforce.employment.propose",
            tenant_id=record.tenant_id, legal_employer_id=record.legal_employer_id,
        )
        if not isinstance(principal, str) or not principal:
            raise PeopleDomainError("Employer authority not attested")
        previous = self.repository.latest(
            tenant_id=record.tenant_id, employer_id=record.legal_employer_id,
            person_ref=record.person_ref,
        )
        if previous:
            if record.version != previous.version + 1 or record.effective_from <= previous.effective_from:
                raise PeopleDomainError("Employment version must move forward")
        elif record.version != 1:
            raise PeopleDomainError("First employment version must be one")
        # This is a port requirement, not an in-process lock. A real Postgres
        # adapter must CAS under the same transaction as its append operation.
        self.repository.append_if_version(record, previous_version=previous.version if previous else None)
