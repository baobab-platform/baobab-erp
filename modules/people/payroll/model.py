"""Payroll workflow facts intentionally exclude pay amounts and individual earnings."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import re


class PayrollPolicyError(ValueError):
    """An authority/qualification failure without employee information."""


def _ref(value: str, *, scope: bool = False) -> None:
    pattern = r"[A-Za-z0-9_.:-]{3,160}" if scope else r"[A-Za-z0-9_.:/-]{3,160}"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise PayrollPolicyError("Invalid payroll reference")


@dataclass(frozen=True, slots=True)
class PayrollDraft:
    run_ref: str
    version: int
    tenant_id: str
    legal_employer_id: str
    maker_ref: str
    period_from: date
    period_until: date
    statutory_jurisdiction: str
    currency: str
    rule_pack_sha256: str
    correction_of_run_ref: str | None = None

    def __post_init__(self) -> None:
        for value in (self.run_ref, self.maker_ref):
            _ref(value)
        for value in (self.tenant_id, self.legal_employer_id):
            _ref(value, scope=True)
        if self.correction_of_run_ref is not None:
            _ref(self.correction_of_run_ref)
            if self.correction_of_run_ref == self.run_ref:
                raise PayrollPolicyError("Correction must name a prior run")
        if type(self.version) is not int or self.version < 1:
            raise PayrollPolicyError("Invalid payroll run version")
        if type(self.period_from) is not date or type(self.period_until) is not date or self.period_until < self.period_from:
            raise PayrollPolicyError("Invalid payroll period")
        if not isinstance(self.statutory_jurisdiction, str) or not re.fullmatch(r"[A-Z]{2}", self.statutory_jurisdiction):
            raise PayrollPolicyError("Invalid statutory jurisdiction")
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise PayrollPolicyError("Invalid payroll currency")
        if not isinstance(self.rule_pack_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.rule_pack_sha256):
            raise PayrollPolicyError("Immutable rule pack digest required")


@dataclass(frozen=True, slots=True)
class VerifiedCalculation:
    """Only a trusted evidence-verifier adapter may supply this result."""
    run_ref: str
    version: int
    tenant_id: str
    legal_employer_id: str
    statutory_jurisdiction: str
    currency: str
    rule_pack_sha256: str
    expires_at: datetime
    independently_qualified: bool
    complete: bool
    evidence_reference: str

    def matches(self, draft: PayrollDraft, *, now: datetime) -> bool:
        return (
            (self.run_ref, self.version, self.tenant_id, self.legal_employer_id,
             self.statutory_jurisdiction, self.currency, self.rule_pack_sha256)
            == (draft.run_ref, draft.version, draft.tenant_id, draft.legal_employer_id,
                draft.statutory_jurisdiction, draft.currency, draft.rule_pack_sha256)
            and bool(self.evidence_reference)
            and self.independently_qualified is True
            and self.complete is True
            and isinstance(self.expires_at, datetime)
            and self.expires_at.tzinfo is not None
            and self.expires_at > now
        )
