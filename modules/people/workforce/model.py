"""Employer-scoped, effective-dated employment versions; never store raw PII here."""
from dataclasses import dataclass
from datetime import date
import re


class PeopleDomainError(ValueError):
    """Safe business denial; never include confidential employee input."""


def _reference(value: str, label: str) -> None:
    if not isinstance(value, str) or not (3 <= len(value) <= 160) or value != value.strip() or any(c.isspace() for c in value):
        raise PeopleDomainError(f"Invalid {label}")


@dataclass(frozen=True, slots=True)
class EmploymentVersion:
    tenant_id: str
    legal_employer_id: str
    person_ref: str  # Opaque pseudonymous reference, not name, tax number or IAM identity
    version: int
    effective_from: date
    effective_until: date | None
    work_jurisdiction: str
    tax_jurisdiction: str
    pay_currency: str
    contract_evidence_ref: str
    state: str = "PROPOSED"  # Not activated or accepted for payroll by this scaffold

    def __post_init__(self) -> None:
        for label in ("tenant_id", "legal_employer_id", "person_ref", "contract_evidence_ref"):
            _reference(getattr(self, label), label)
        if type(self.version) is not int or self.version < 1:
            raise PeopleDomainError("Invalid employment version")
        if not isinstance(self.effective_from, date) or (
            self.effective_until is not None and (
                not isinstance(self.effective_until, date) or self.effective_until <= self.effective_from
            )
        ):
            raise PeopleDomainError("Invalid employment effective window")
        for label in ("work_jurisdiction", "tax_jurisdiction"):
            value = getattr(self, label)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{2}", value):
                raise PeopleDomainError(f"Invalid {label}")
        if not isinstance(self.pay_currency, str) or not re.fullmatch(r"[A-Z]{3}", self.pay_currency):
            raise PeopleDomainError("Invalid payroll currency")
        if self.state != "PROPOSED":
            raise PeopleDomainError("Employment activation is unavailable pending Shared/CP authority")
