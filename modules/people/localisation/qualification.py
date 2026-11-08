"""Independent statutory qualification gate; deliberately no self-certification.

No payroll rates or legal claims are embedded. ZA PAYE/UIF/SDL/ETI and UG
URA/NSSF each require externally signed official/reference cases plus
licensed provider evidence before this gate can report qualified.
"""
from dataclasses import dataclass
from datetime import datetime, timezone


class StatutoryQualificationHold(ValueError):
    pass


REQUIRED = {
    "ZA": frozenset(("PAYE", "UIF", "SDL", "ETI")),
    "UG": frozenset(("URA", "NSSF")),
}


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    tenant_id: str
    legal_employer_id: str
    provider_id: str
    jurisdiction: str
    qualification_receipt_ref: str
    rule_pack_sha256: str
    verified_obligations: frozenset[str]
    reviewer_ref: str
    provider_licence_evidence_ref: str
    witness_run_refs: tuple[str, ...]
    independently_signed: bool
    effective_from: datetime
    effective_until: datetime


class QualificationRegister:
    """Unpopulated by default. Records require separate external audit custody.

    This is a readback checker, not a method for providers to mark themselves
    qualified. A qualifying record is never created by this module.
    """
    def __init__(self, reader=None):
        self._reader = reader

    def independently_qualified(self, *, tenant_id: str, legal_employer_id: str,
        provider_id: str, jurisdiction: str, qualification_receipt_ref: str,
        rule_pack_sha256: str, at: datetime) -> bool:
        if self._reader is None or jurisdiction not in REQUIRED or not isinstance(at, datetime) or at.tzinfo is None:
            return False
        record = self._reader.read_current(
            tenant_id=tenant_id, legal_employer_id=legal_employer_id,
            provider_id=provider_id, jurisdiction=jurisdiction,
            qualification_receipt_ref=qualification_receipt_ref,
        )
        return (
            isinstance(record, QualificationEvidence)
            and record.tenant_id == tenant_id and record.legal_employer_id == legal_employer_id
            and record.provider_id == provider_id and record.jurisdiction == jurisdiction
            and record.qualification_receipt_ref == qualification_receipt_ref
            and record.rule_pack_sha256 == rule_pack_sha256
            and record.verified_obligations == REQUIRED[jurisdiction]
            and record.independently_signed is True
            and bool(record.reviewer_ref) and bool(record.provider_licence_evidence_ref)
            and len(record.witness_run_refs) >= 2
            and record.effective_from.tzinfo is not None
            and record.effective_until.tzinfo is not None
            and record.effective_from <= at < record.effective_until
        )


# This is a product gate, not a legal certification authority. Signatures,
# reviewer independence, licence status and statutory math MUST be verified
# by the independent source behind the reader, not by this dataclass.
