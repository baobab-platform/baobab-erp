"""Independent signed statutory review gate (ADR-ERP-023 / ADR-SHARED-045).

The trust anchor is a separately installed reviewer public key, never a
payroll provider's own signing key. No rate values, statutory certification,
provider licence or privileged stage is bundled in this repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
import re
from typing import Mapping, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


REQUIRED = {
    "ZA": frozenset(("PAYE", "UIF", "SDL", "ETI")),
    "UG": frozenset(("URA", "NSSF")),
}

REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
PAYLOAD_FIELDS = frozenset({
    "tenant_id", "legal_employer_id", "provider_id", "jurisdiction",
    "qualification_receipt_ref", "rule_pack_sha256", "verified_obligations",
    "golden_vector_refs", "reviewer_ref", "reviewer_independence_ref",
    "provider_licence_evidence_ref", "witness_run_refs",
    "effective_from", "effective_until",
})


class ReviewSource(Protocol):
    def read_current(self, *, tenant_id: str, legal_employer_id: str,
                     provider_id: str, jurisdiction: str,
                     qualification_receipt_ref: str) -> bytes | None: ...


def _read_unique(raw: bytes) -> dict | None:
    if not isinstance(raw, bytes) or len(raw) > 32768:
        return None
    def pairs(elements):
        result = {}
        for key, value in elements:
            if key in result:
                raise ValueError("duplicate signed review key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    """Immutable signed reviewer assertion, never producer/self-declared."""
    tenant_id: str
    legal_employer_id: str
    provider_id: str
    jurisdiction: str
    qualification_receipt_ref: str
    rule_pack_sha256: str
    verified_obligations: frozenset[str]
    golden_vector_refs: Mapping[str, str]
    reviewer_ref: str
    reviewer_independence_ref: str
    provider_licence_evidence_ref: str
    witness_run_refs: tuple[str, ...]
    effective_from: datetime
    effective_until: datetime


class QualificationRegister:
    """Fails closed until separately verified reviewer signed evidence exists.

    The reviewer key ring MUST come from independently governed trust custody
    and MUST NOT include a key supplied by the selected payroll provider.
    """
    def __init__(self, reader: ReviewSource | None = None,
                 reviewer_keys: Mapping[str, bytes] | None = None):
        self._reader = reader
        self._keys = dict(reviewer_keys or {})

    def independently_qualified(self, *, tenant_id: str, legal_employer_id: str,
        provider_id: str, jurisdiction: str, qualification_receipt_ref: str,
        rule_pack_sha256: str, at: datetime) -> bool:
        if (self._reader is None or not self._keys or jurisdiction not in REQUIRED
                or not isinstance(at, datetime) or at.tzinfo is None):
            return False
        try:
            wire = self._reader.read_current(
                tenant_id=tenant_id, legal_employer_id=legal_employer_id,
                provider_id=provider_id, jurisdiction=jurisdiction,
                qualification_receipt_ref=qualification_receipt_ref,
            )
        except Exception:
            return False
        doc = _read_unique(wire)
        if doc is None or set(doc) != {"payload", "signature"}:
            return False
        payload, encoded_signature = doc["payload"], doc["signature"]
        if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS or not isinstance(encoded_signature, str):
            return False
        reviewer = payload["reviewer_ref"]
        key = self._keys.get(reviewer) if isinstance(reviewer, str) else None
        if (not isinstance(key, bytes) or len(key) != 32 or reviewer == provider_id):
            return False
        try:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False).encode("utf-8")
            signature = base64.b64decode(encoded_signature, validate=True)
            if len(signature) != 64:
                return False
            Ed25519PublicKey.from_public_bytes(key).verify(signature, canonical)
        except (ValueError, TypeError, InvalidSignature, OverflowError):
            return False
        issued = _utc(payload["effective_from"])
        until = _utc(payload["effective_until"])
        obligations = payload["verified_obligations"]
        vectors = payload["golden_vector_refs"]
        runs = payload["witness_run_refs"]
        if (payload["tenant_id"] != tenant_id or payload["legal_employer_id"] != legal_employer_id
                or payload["provider_id"] != provider_id or payload["jurisdiction"] != jurisdiction
                or payload["qualification_receipt_ref"] != qualification_receipt_ref
                or payload["rule_pack_sha256"] != rule_pack_sha256
                or not DIGEST.fullmatch(rule_pack_sha256)
                or not isinstance(obligations, list) or len(obligations) != len(REQUIRED[jurisdiction])
                or len(set(map(str, obligations))) != len(obligations)
                or frozenset(obligations) != REQUIRED[jurisdiction]
                or not isinstance(vectors, dict) or set(vectors) != REQUIRED[jurisdiction]
                or not all(isinstance(v, str) and REF.fullmatch(v) for v in vectors.values())
                or not isinstance(runs, list) or len(runs) < 2 or len(set(map(str, runs))) != len(runs)
                or not all(isinstance(v, str) and REF.fullmatch(v) for v in runs)
                or not isinstance(payload["reviewer_independence_ref"], str)
                or not REF.fullmatch(payload["reviewer_independence_ref"])
                or not isinstance(payload["provider_licence_evidence_ref"], str)
                or not REF.fullmatch(payload["provider_licence_evidence_ref"])
                or issued is None or until is None
                or not issued <= at.astimezone(timezone.utc) < until):
            return False
        return True


# A valid signature verifies the reviewer's assertion, not its truth.
# Independent assessors must separately verify source law, licences,
# golden-vector outcomes, reviewer independence and actual witness runs.
