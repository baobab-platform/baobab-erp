"""Synthetic cryptographic conformance; NOT real payroll provider qualification."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import base64
import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from people.providers.selection import CPProviderSelector, ProviderSelectionDenied
from people.providers.evidence import (
    ExternalEvidenceAdapter, NativeDraftOnlyAdapter, SelectedCalculationVerifier,
)
from people.localisation.qualification import QualificationRegister
from people.payroll.model import PayrollDraft, PayrollPolicyError
from people.payroll.service import PayrollEligibilityGate


NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
CORRELATION = "12345678-1234-4234-8234-123456789012"
RECEIPT = "receipt_synthetic01"
RULE_SHA = "a" * 64


class SyntheticTokens:
    def __init__(self):
        self.calls = []

    def access_token(self, audience, scopes):
        self.calls.append((audience, scopes))
        if audience == "baobab-control-plane":
            assert scopes == ("context:resolve", "people:provider:read")
        elif audience == "provider_synthetic01":
            assert scopes == ("payroll:evidence:verify",)
        else:
            raise AssertionError("unregistered provider audience")
        return "test-bearer"


def draft(**changes):
    return replace(PayrollDraft(
        run_ref="run_synthetic01", version=1, tenant_id="tn_synthetic01",
        legal_employer_id="SYNTHETIC-EMPLOYER", maker_ref="maker_synthetic01",
        period_from=date(2026, 10, 1), period_until=date(2026, 10, 31),
        statutory_jurisdiction="ZA", currency="ZAR",
        rule_pack_sha256=RULE_SHA,
    ), **changes)


def selection(**changes):
    current = {
        "tenant_id": "tn_synthetic01",
        "legal_employer_id": "SYNTHETIC-EMPLOYER",
        "jurisdiction": "ZA",
        "capability_key": "payroll.evidence.attest",
        "binding_id": "bind_synthetic01",
        "provider_id": "provider_synthetic01",
        "binding_revision": 3,
        "source_of_record": "EXTERNAL",
        "qualification_receipt_ref": "qualification_synthetic01",
        "effective_from": (NOW - timedelta(minutes=1)).isoformat(),
        "verified_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=25)).isoformat(),
    }
    current.update(changes)
    return {
        "selection": current, "revision": current["binding_revision"],
        "status": "ACTIVE", "portability_enabled": True,
        "decision_ref": "res_synthetic01",
    }


def receipt(**changes):
    current = {
        "run_ref": "run_synthetic01", "version": 1,
        "tenant_id": "tn_synthetic01", "legal_employer_id": "SYNTHETIC-EMPLOYER",
        "jurisdiction": "ZA", "currency": "ZAR", "rule_pack_sha256": RULE_SHA,
        "binding_id": "bind_synthetic01", "provider_id": "provider_synthetic01",
        "binding_revision": 3, "qualification_receipt_ref": "qualification_synthetic01",
        "evidence_ref": RECEIPT, "issued_at": (NOW - timedelta(seconds=1)).isoformat(),
        "expires_at": (NOW + timedelta(seconds=10)).isoformat(),
        "verification_status": "VERIFIED", "complete": True,
    }
    current.update(changes)
    return current


class StatutoryWitness:
    def __init__(self, qualified=True):
        self.qualified = qualified
        self.calls = 0

    def independently_qualified(self, *, tenant_id, legal_employer_id, provider_id,
                                jurisdiction, qualification_receipt_ref, rule_pack_sha256, at):
        self.calls += 1
        return (
            self.qualified and tenant_id == "tn_synthetic01"
            and legal_employer_id == "SYNTHETIC-EMPLOYER"
            and provider_id == "provider_synthetic01" and jurisdiction == "ZA"
            and rule_pack_sha256 == RULE_SHA
            and qualification_receipt_ref == "qualification_synthetic01" and at == NOW
        )


class Store:
    def __init__(self, value):
        self.value = value

    def latest(self, *, tenant_id, employer_id, run_ref):
        if self.value and (self.value.tenant_id, self.value.legal_employer_id,
                           self.value.run_ref) == (tenant_id, employer_id, run_ref):
            return self.value
        return None


class Approval:
    def attest_approver(self, *, proof, tenant_id, legal_employer_id, run_ref):
        if (proof, tenant_id, legal_employer_id, run_ref) != (
            "checker-proof", "tn_synthetic01", "SYNTHETIC-EMPLOYER", "run_synthetic01"
        ):
            raise PayrollPolicyError("Independent checker denied")
        return "checker_synthetic01"


class PeopleBYOPTests(unittest.TestCase):
    def setUp(self):
        self.tokens = SyntheticTokens()
        self.selected = selection()
        self.signed = receipt()
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.witness = StatutoryWitness()
        self.store = Store(draft())
        self.cp_calls = []
        self.provider_calls = []

    def cp_transport(self, url, request, token):
        obj = json.loads(request)
        self.cp_calls.append(obj)
        self.assertEqual(token, "test-bearer")
        self.assertEqual(url, "https://cp.example.test/internal/people/v1/provider-selection/resolve")
        self.assertEqual(set(obj), {
            "context_id", "correlation_id", "capability_key", "required_contract_version",
        })
        return json.dumps(self.selected, separators=(",", ":")).encode()

    def provider_transport(self, url, request, token):
        self.assertEqual(token, "test-bearer")
        self.assertEqual(url, "https://hris.example.test/v1/payroll/evidence/verify")
        self.provider_calls.append(json.loads(request))
        content = json.dumps(self.signed, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()
        signature = self.private.sign(content)
        return json.dumps({
            "payload": self.signed, "key_id": "provider-public-key-1",
            "signature": base64.b64encode(signature).decode(),
        }).encode()

    def adapter(self, *, witness=None, source=None):
        selector = CPProviderSelector(
            "https://cp.example.test", self.tokens, self.cp_transport,
        )
        provider = source if source is not None else ExternalEvidenceAdapter(
            "tn_synthetic01", "SYNTHETIC-EMPLOYER", "ZA",
            "provider_synthetic01", "https://hris.example.test",
            "provider-public-key-1", self.public, self.tokens,
            self.provider_transport,
        )
        return SelectedCalculationVerifier(
            selector, {("tn_synthetic01", "SYNTHETIC-EMPLOYER",
                        "ZA", "provider_synthetic01"): provider},
            witness if witness is not None else self.witness,
            draft_reader=self.store,
            context_id="ctx_synthetic01", correlation_id=CORRELATION,
            clock=lambda: NOW,
        )

    def verify(self, verifier=None):
        adapter = verifier if verifier is not None else self.adapter()
        return adapter.verify(
            evidence_ref=RECEIPT, tenant_id="tn_synthetic01",
            employer_id="SYNTHETIC-EMPLOYER",
            run_ref="run_synthetic01", version=1,
        )

    def test_signed_selected_external_provider_is_only_eligibility_input(self):
        result = self.verify()
        self.assertTrue(result.complete)
        self.assertTrue(result.independently_qualified)
        self.assertEqual(self.witness.calls, 1)
        self.assertEqual(len(self.cp_calls), 1)
        self.assertEqual(self.cp_calls[0]["capability_key"], "payroll.evidence.attest")
        self.assertEqual(self.provider_calls[0], {
            "tenant_id": "tn_synthetic01", "legal_employer_id": "SYNTHETIC-EMPLOYER",
            "jurisdiction": "ZA", "binding_id": "bind_synthetic01",
            "binding_revision": 3,
            "run_ref": "run_synthetic01", "run_version": 1, "evidence_ref": RECEIPT,
        })
        self.assertFalse(hasattr(result, "payment_authorization"))
        self.assertFalse(hasattr(result, "journal_posted"))

    def test_evidence_issued_after_cp_observation_is_valid_when_current_and_signed(self):
        # CP selection is observed first; the provider may sign the receipt
        # afterwards in the same bounded verification flow.
        self.selected = selection(verified_at=(NOW - timedelta(seconds=2)).isoformat())
        self.signed = receipt(issued_at=(NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(self.verify().evidence_reference, RECEIPT)

    def test_cp_verified_during_real_transport_after_request_clock_is_accepted(self):
        # The request clock is captured before HTTPS, while CP verified_at
        # is recorded during/after the roundtrip, not at request start.
        self.selected = selection(
            verified_at=(NOW + timedelta(seconds=2)).isoformat(),
            expires_at=(NOW + timedelta(seconds=27)).isoformat(),
        )
        selector = CPProviderSelector("https://cp.example.test", self.tokens, self.cp_transport)
        accepted = selector.resolve(
            context_id="ctx_synthetic01", correlation_id=CORRELATION,
            capability_key="payroll.evidence.attest", tenant_id="tn_synthetic01",
            legal_employer_id="SYNTHETIC-EMPLOYER", jurisdiction="ZA", now=NOW,
        )
        self.assertEqual(accepted.provider_id, "provider_synthetic01")

    def test_future_issued_evidence_remains_refused(self):
        self.signed = receipt(issued_at=(NOW + timedelta(seconds=1)).isoformat())
        with self.assertRaises(PayrollPolicyError):
            self.verify()

    def test_works_with_existing_independent_checker_gate_without_approving(self):
        result = PayrollEligibilityGate(Approval(), self.adapter()).check(
            draft(), authority_proof="checker-proof",
            calculation_evidence_ref=RECEIPT, now=NOW,
        )
        self.assertEqual(result.checker_ref, "checker_synthetic01")
        self.assertFalse(hasattr(result, "payment_authorisation"))

    def test_cp_provider_scope_and_freshness_are_mandatory(self):
        for label, changed in {
            "foreign tenant": {"tenant_id": "tn_other"},
            "foreign employer": {"legal_employer_id": "OTHER-EMPLOYER"},
            "wrong jurisdiction": {"jurisdiction": "UG"},
            "silent fallback": {"source_of_record": "AUTO_FALLBACK"},
            "unknown provider": {"provider_id": "provider_other"},
            "revoked lease": {"expires_at": NOW.isoformat()},
            "unbounded future receipt": {"verified_at": (NOW + timedelta(seconds=8)).isoformat()},
            "stale selection": {"verified_at": (NOW - timedelta(seconds=31)).isoformat()},
            "no qualification": {"qualification_receipt_ref": ""},
            "foreign binding": {"binding_id": "bind_other"},
        }.items():
            with self.subTest(label=label):
                self.selected = selection(**changed)
                self.provider_calls.clear()
                with self.assertRaises((ProviderSelectionDenied, PayrollPolicyError)):
                    self.verify()
                # A binding switch may be a legitimate CP decision; its
                # selected read-only provider adapter can be asked to
                # verify, but an old receipt naming the previous binding
                # is rejected before it can become eligibility.
                if label != "foreign binding":
                    self.assertFalse(self.provider_calls)
        self.selected = selection()
        self.selected["portability_enabled"] = False
        self.provider_calls.clear()
        with self.assertRaises(ProviderSelectionDenied):
            self.verify()
        self.assertFalse(self.provider_calls)

    def test_invalid_scope_cannot_be_sent_to_cp(self):
        selector = CPProviderSelector("https://cp.example.test", self.tokens, self.cp_transport)
        with self.assertRaises(ProviderSelectionDenied):
            selector.resolve(context_id="ctx_synthetic01", correlation_id=CORRELATION,
                             capability_key="payroll.run.finalize", tenant_id="tn_synthetic01",
                             legal_employer_id="SYNTHETIC-EMPLOYER", jurisdiction="ZA", now=NOW)
        self.assertEqual(self.cp_calls, [])

    def test_signed_payload_binding_replay_and_provider_checks(self):
        variants = {
            "wrong legal employer": {"legal_employer_id": "OTHER-EMPLOYER"},
            "wrong tenant": {"tenant_id": "tn_other"},
            "wrong country": {"jurisdiction": "UG"},
            "wrong binding": {"binding_id": "bind_other"},
            "wrong provider": {"provider_id": "provider_other"},
            "stale version": {"version": 2},
            "different digest": {"rule_pack_sha256": "b"*64},
            "evidence replay": {"evidence_ref": "receipt_old"},
            "incomplete": {"complete": False},
            "unknown": {"verification_status": "UNKNOWN"},
            "expired": {"expires_at": NOW.isoformat()},
        }
        for label, values in variants.items():
            with self.subTest(label=label):
                self.signed = receipt(**values)
                with self.assertRaises(PayrollPolicyError):
                    self.verify()
        self.signed = receipt()
        self.assertEqual(self.verify().evidence_reference, RECEIPT)

    def test_missing_independent_qualification_and_native_fail_closed(self):
        with self.assertRaises(PayrollPolicyError):
            self.verify(self.adapter(witness=StatutoryWitness(False)))
        with self.assertRaises(PayrollPolicyError):
            self.verify(self.adapter(witness=QualificationRegister()))
        with self.assertRaises(ProviderSelectionDenied):
            self.verify(self.adapter(source=NativeDraftOnlyAdapter()))

    def test_external_adapter_is_employer_bound_even_when_provider_id_matches(self):
        verifier = self.adapter()
        adapter = verifier._adapters[(
            "tn_synthetic01", "SYNTHETIC-EMPLOYER", "ZA", "provider_synthetic01",
        )]
        from people.providers.selection import ProviderSelection
        selection = ProviderSelection(
            "tn_other", "SYNTHETIC-EMPLOYER", "ZA", "payroll.evidence.attest",
            "bind_synthetic01", "provider_synthetic01", 3, "EXTERNAL",
            "qualification_synthetic01", NOW, NOW + timedelta(seconds=10),
        )
        with self.assertRaises(ProviderSelectionDenied):
            adapter.read(selected=selection, draft=draft(), evidence_ref=RECEIPT, now=NOW)
        self.assertEqual(self.provider_calls, [])

    def test_exact_draft_version_and_employer_required_before_cp(self):
        with self.assertRaises(PayrollPolicyError):
            self.adapter().verify(evidence_ref=RECEIPT, tenant_id="tn_other",
                                  employer_id="SYNTHETIC-EMPLOYER",
                                  run_ref="run_synthetic01", version=1)
        with self.assertRaises(PayrollPolicyError):
            self.adapter().verify(evidence_ref=RECEIPT, tenant_id="tn_synthetic01",
                                  employer_id="SYNTHETIC-EMPLOYER",
                                  run_ref="run_synthetic01", version=2)
        self.assertEqual(self.cp_calls, [])


if __name__ == "__main__":
    unittest.main()
