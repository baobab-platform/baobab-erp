"""Scoped payroll evidence adapters: no calculation, filing, GL or money movement.

An external provider may return an independently verifiable Ed25519-signed
receipt, but it CANNOT self-assert statutory qualification. The verifier
checks provider signature and a *separate* registered local qualification
authority before producing VerifiedCalculation eligibility facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
import re
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .selection import (
    CPProviderSelector, ProviderSelectionDenied, ProviderSelection, Transport,
    TokenSource, _endpoint, _timestamp, _unique_json, verified_https_post,
)
from ..payroll.model import PayrollDraft, VerifiedCalculation, PayrollPolicyError


class StatutoryQualificationAuthority(Protocol):
    def independently_qualified(self, *, tenant_id: str, legal_employer_id: str,
        provider_id: str, jurisdiction: str, qualification_receipt_ref: str,
        rule_pack_sha256: str, at: datetime) -> bool:
        """Read a current independent reviewer/signature; no provider self-approval."""


class PayrollDraftReader(Protocol):
    def latest(self, *, tenant_id: str, employer_id: str,
               run_ref: str) -> PayrollDraft | None: ...


class EvidenceSource(Protocol):
    def read(self, *, selected: ProviderSelection, draft: PayrollDraft,
             evidence_ref: str, now: datetime) -> dict: ...


@dataclass(frozen=True, slots=True)
class ExternalEvidenceAdapter:
    """One privately configured provider endpoint and trusted signing key."""
    # One adapter instance is bound to ONE employer account. The provider
    # credential source must independently be configured for that account;
    # a globally reusable vendor bearer is not employer authorisation.
    tenant_id: str
    legal_employer_id: str
    jurisdiction: str
    provider_id: str
    endpoint: str
    key_id: str
    verification_key: bytes
    tokens: TokenSource
    transport: Transport = verified_https_post

    def __post_init__(self):
        _endpoint(self.endpoint, "")
        if len(self.verification_key) != 32 or not self.key_id:
            raise ProviderSelectionDenied("Provider public-key configuration required")

    def read(self, *, selected: ProviderSelection, draft: PayrollDraft,
             evidence_ref: str, now: datetime) -> dict:
        if (selected.provider_id != self.provider_id or selected.source_of_record != "EXTERNAL"
                or selected.tenant_id != self.tenant_id
                or selected.legal_employer_id != self.legal_employer_id
                or selected.jurisdiction != self.jurisdiction
                or draft.tenant_id != self.tenant_id
                or draft.legal_employer_id != self.legal_employer_id
                or draft.statutory_jurisdiction != self.jurisdiction):
            raise ProviderSelectionDenied("Selected provider adapter mismatch")
        data = json.dumps({
            "tenant_id": selected.tenant_id,
            "legal_employer_id": selected.legal_employer_id,
            "jurisdiction": selected.jurisdiction,
            "binding_id": selected.binding_id,
            "binding_revision": selected.binding_revision,
            "run_ref": draft.run_ref, "run_version": draft.version,
            "evidence_ref": evidence_ref,
        }, separators=(",", ":")).encode()
        token = self.tokens.access_token(self.provider_id, ("payroll:evidence:verify",))
        raw = _unique_json(self.transport(_endpoint(self.endpoint, "/v1/payroll/evidence/verify"), data, token))
        if set(raw) != {"payload", "key_id", "signature"} or not isinstance(raw["payload"], dict):
            raise ProviderSelectionDenied("Invalid provider signed evidence")
        if raw["key_id"] != self.key_id:
            raise ProviderSelectionDenied("Unregistered provider signing key")
        encoded = json.dumps(raw["payload"], sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        try:
            signature = base64.b64decode(raw["signature"], validate=True)
            if len(signature) != 64:
                raise ValueError("bad signature length")
            Ed25519PublicKey.from_public_bytes(self.verification_key).verify(signature, encoded)
        except (ValueError, InvalidSignature, TypeError) as error:
            raise ProviderSelectionDenied("Provider evidence signature invalid") from error
        return raw["payload"]


class NativeDraftOnlyAdapter:
    """The current PG17 native People scaffold is deliberately unqualified."""
    def read(self, *, selected: ProviderSelection, draft: PayrollDraft,
             evidence_ref: str, now: datetime) -> dict:
        raise ProviderSelectionDenied("Native payroll calculator not independently qualified")


_RECEIPT = {
    "run_ref", "version", "tenant_id", "legal_employer_id", "jurisdiction",
    "currency", "rule_pack_sha256", "binding_id", "provider_id", "binding_revision",
    "qualification_receipt_ref", "evidence_ref", "issued_at", "expires_at",
    "verification_status", "complete",
}


class SelectedCalculationVerifier:
    """Conforming PayrollEligibilityGate verifier: CP chooses, adapter proves.

    A signed provider receipt is only an eligibility input, never final payroll
    approval or payroll payment authority. It checks CP again on each call.
    """

    def __init__(self, selector: CPProviderSelector,
                 adapters: dict[tuple[str, str, str, str], EvidenceSource],
                 statutory: StatutoryQualificationAuthority, *, draft_reader: PayrollDraftReader,
                 context_id: str, correlation_id: str, clock):
        self._selector = selector
        self._adapters = dict(adapters)
        self._statutory = statutory
        self._draft_reader = draft_reader
        self._context_id = context_id
        self._correlation_id = correlation_id
        self._clock = clock

    def verify(self, *, evidence_ref: str, tenant_id: str, employer_id: str,
               run_ref: str, version: int) -> VerifiedCalculation:
        """Implement the existing PayrollEligibilityGate verifier port."""
        if type(version) is not int or version < 1:
            raise PayrollPolicyError("Invalid payroll draft version")
        draft = self._draft_reader.latest(
            tenant_id=tenant_id, employer_id=employer_id, run_ref=run_ref,
        )
        if (not isinstance(draft, PayrollDraft)
                or draft.version != version or draft.tenant_id != tenant_id
                or draft.legal_employer_id != employer_id or draft.run_ref != run_ref):
            raise PayrollPolicyError("Exact immutable employer payroll draft missing")
        return self.verify_draft(draft, evidence_ref=evidence_ref)

    def verify_draft(self, draft: PayrollDraft, *, evidence_ref: str) -> VerifiedCalculation:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise PayrollPolicyError("Verification clock unavailable")
        now = now.astimezone(timezone.utc)
        selected = self._selector.resolve(
            context_id=self._context_id, correlation_id=self._correlation_id,
            capability_key="payroll.evidence.attest", tenant_id=draft.tenant_id,
            legal_employer_id=draft.legal_employer_id,
            jurisdiction=draft.statutory_jurisdiction, now=now,
        )
        adapter = self._adapters.get((
            selected.tenant_id, selected.legal_employer_id,
            selected.jurisdiction, selected.provider_id,
        ))
        if adapter is None:
            raise PayrollPolicyError("Selected payroll provider has no qualified adapter")
        received = adapter.read(selected=selected, draft=draft, evidence_ref=evidence_ref, now=now)
        if not isinstance(received, dict) or set(received) != _RECEIPT:
            raise PayrollPolicyError("Invalid provider evidence shape")
        issued = _timestamp(received["issued_at"])
        expiry = _timestamp(received["expires_at"])
        if (received["run_ref"] != draft.run_ref or received["version"] != draft.version
                or received["tenant_id"] != draft.tenant_id
                or received["legal_employer_id"] != draft.legal_employer_id
                or received["jurisdiction"] != draft.statutory_jurisdiction
                or received["currency"] != draft.currency
                or received["rule_pack_sha256"] != draft.rule_pack_sha256
                or received["binding_id"] != selected.binding_id
                or received["provider_id"] != selected.provider_id
                or received["binding_revision"] != selected.binding_revision
                or received["qualification_receipt_ref"] != selected.qualification_receipt_ref
                or received["evidence_ref"] != evidence_ref
                or received["verification_status"] != "VERIFIED"
                or received["complete"] is not True
                or not issued <= now < expiry
                or issued > selected.verified_at
                or expiry > selected.expires_at
                or (expiry - issued).total_seconds() > 30):
            raise PayrollPolicyError("Provider evidence not current or scope-exact")
        if not self._statutory.independently_qualified(
            tenant_id=draft.tenant_id, legal_employer_id=draft.legal_employer_id,
            provider_id=selected.provider_id, jurisdiction=draft.statutory_jurisdiction,
            qualification_receipt_ref=selected.qualification_receipt_ref,
            rule_pack_sha256=draft.rule_pack_sha256, at=now,
        ):
            raise PayrollPolicyError("Independent statutory qualification required")
        return VerifiedCalculation(
            draft.run_ref, draft.version, draft.tenant_id, draft.legal_employer_id,
            draft.statutory_jurisdiction, draft.currency, draft.rule_pack_sha256,
            expiry, True, True, evidence_ref,
        )
