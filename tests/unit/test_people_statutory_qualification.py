"""Synthetic independent reviewer signature tests: no real statutory rates."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import base64
import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from people.localisation.qualification import QualificationRegister

NOW = datetime(2026, 11, 8, 13, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def payload(jurisdiction="ZA"):
    obligations = ["PAYE", "UIF", "SDL", "ETI"] if jurisdiction == "ZA" else ["URA", "NSSF"]
    return {
        "tenant_id": "tn_synthetic01",
        "legal_employer_id": "SYNTHETIC-EMPLOYER",
        "provider_id": "provider_synthetic01",
        "jurisdiction": jurisdiction,
        "qualification_receipt_ref": "cert_synthetic01",
        "rule_pack_sha256": SHA,
        "verified_obligations": obligations,
        "golden_vector_refs": {name: "vector_" + name.lower() for name in obligations},
        "reviewer_ref": "reviewer_synthetic01",
        "reviewer_independence_ref": "independent_declaration_synthetic01",
        "provider_licence_evidence_ref": "licence_document_synthetic01",
        "witness_run_refs": ["witness_parallel_01", "witness_parallel_02"],
        "effective_from": (NOW-timedelta(days=1)).isoformat(),
        "effective_until": (NOW+timedelta(days=1)).isoformat(),
    }


class Source:
    def __init__(self, value): self.value = value
    def read_current(self, **kwargs): return self.value


class ReviewSignatureTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.document = payload()

    def wire(self):
        canonical = json.dumps(self.document, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode()
        return json.dumps({
            "payload": self.document,
            "signature": base64.b64encode(self.private.sign(canonical)).decode(),
        }).encode()

    def checked(self, *, data=None, keys=None, jurisdiction="ZA", rule=SHA):
        register = QualificationRegister(
            Source(data if data is not None else self.wire()),
            keys if keys is not None else {"reviewer_synthetic01": self.public},
        )
        return register.independently_qualified(
            tenant_id="tn_synthetic01", legal_employer_id="SYNTHETIC-EMPLOYER",
            provider_id="provider_synthetic01", jurisdiction=jurisdiction,
            qualification_receipt_ref="cert_synthetic01", rule_pack_sha256=rule, at=NOW,
        )

    def test_signed_reviewer_statement_is_only_a_shape_acceptance(self):
        self.assertTrue(self.checked())
        self.assertFalse(QualificationRegister().independently_qualified(
            tenant_id="tn_synthetic01", legal_employer_id="SYNTHETIC-EMPLOYER",
            provider_id="provider_synthetic01", jurisdiction="ZA",
            qualification_receipt_ref="cert_synthetic01", rule_pack_sha256=SHA, at=NOW,
        ))

    def test_missing_untrusted_and_tampered_reviewer_denied(self):
        self.assertFalse(self.checked(keys={}))
        self.assertFalse(self.checked(keys={"reviewer_synthetic01": b"\x00"*32}))
        self.document["reviewer_ref"] = "provider_synthetic01"
        self.assertFalse(self.checked())
        self.document = payload()
        tampered = json.loads(self.wire())
        tampered["payload"]["provider_id"] = "provider_other"
        self.assertFalse(self.checked(data=json.dumps(tampered).encode()))

    def test_every_jurisdiction_vector_is_mandatory(self):
        self.document["verified_obligations"].remove("ETI")
        self.assertFalse(self.checked())
        self.document = payload()
        self.document["golden_vector_refs"].pop("SDL")
        self.assertFalse(self.checked())
        self.document = payload()
        self.document["witness_run_refs"] = ["witness_parallel_01"]
        self.assertFalse(self.checked())
        self.document = payload()
        self.document["provider_licence_evidence_ref"] = ""
        self.assertFalse(self.checked())

    def test_wrong_country_rule_window_and_unsigned_provider_reply_refused(self):
        self.assertFalse(self.checked(jurisdiction="UG"))
        self.assertFalse(self.checked(rule="b"*64))
        self.document["effective_until"] = (NOW-timedelta(seconds=1)).isoformat()
        self.assertFalse(self.checked())
        self.document = payload()
        tampered = json.loads(self.wire())
        tampered["signature"] = "not-base64"
        self.assertFalse(self.checked(data=json.dumps(tampered).encode()))

    def test_uganda_requires_independent_ug_specific_review(self):
        self.document = payload("UG")
        self.assertTrue(self.checked(jurisdiction="UG"))
        self.assertFalse(self.checked(jurisdiction="ZA"))
        self.document["verified_obligations"] = ["PAYE", "UIF", "SDL", "ETI"]
        self.assertFalse(self.checked(jurisdiction="UG"))


if __name__ == "__main__":
    unittest.main()
