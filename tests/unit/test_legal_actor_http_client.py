"""LA-05D2: the CP HTTP adapter uses the owner workload and cannot mint actor identity."""
import io
import json
import unittest
from datetime import datetime, timezone

from order_to_cash.legal_actor_http_client import HttpControlPlaneLegalActorAssessor
from order_to_cash.legal_actor_gate import (
    LegalActorNotAuthorised, LegalActorOperation, perform_governed_financial_action,
)
from provisioning.control_plane_client import ControlPlaneUnavailable


class Opener:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        return io.BytesIO(json.dumps(self.answer).encode())


REQUEST = {
    "context_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
    "role": "INVOICE_ISSUER",
    "activity": "B2B_EXPORT_INVOICE",
    "market": "ZA",
    "capability": "accounting.customer-invoice.post",
    "operation_reference": "invoice-123",
}


def result(outcome="NO_APPLICABLE_MANDATE"):
    return {
        "context_id": REQUEST["context_id"],
        "operation_reference": REQUEST["operation_reference"],
        "provider_permissions_granted": False,
        "legal_actor_resolution": {
            "outcome": outcome,
            "policy_reference": "ADR-BCP-027/LA-04B",
            "evaluated_at": "2026-10-09T14:00:00Z",
        },
    }


class TestLegalActorHTTPClient(unittest.TestCase):
    def client(self, opener):
        return HttpControlPlaneLegalActorAssessor(
            "https://control-plane.example", lambda: "synthetic-workload-token",
            lambda: "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d",
            opener=opener,
        )

    def test_sends_exact_context_owned_request_without_legal_entity_selector(self):
        opener = Opener(result())
        response = self.client(opener).assess(REQUEST)
        self.assertEqual(response, result())
        req, timeout = opener.calls[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://control-plane.example/internal/legal-actor/v1/assess")
        self.assertEqual(timeout, 3)
        self.assertEqual(json.loads(req.data), REQUEST)
        self.assertEqual(req.get_header("Authorization"), "Bearer synthetic-workload-token")
        self.assertEqual(req.get_header("Cache-control"), "no-store")
        self.assertNotIn("responsible_legal_entity_id", json.loads(req.data))
        self.assertNotIn("tenant_id", json.loads(req.data))
        self.assertNotIn("mandate_id", json.loads(req.data))

    def test_rejects_foreign_malformed_unsupported_and_insecure(self):
        for invalid in (
            {**result(), "context_id": "other"},
            {**result(), "provider_permissions_granted": True},
            {**result(), "legal_actor_resolution": None},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ControlPlaneUnavailable):
                    self.client(Opener(invalid)).assess(REQUEST)
        opener = Opener(result())
        with self.assertRaises(ControlPlaneUnavailable):
            self.client(opener).assess({**REQUEST, "legal_entity_id": "fake"})
        self.assertEqual(opener.calls, [])
        with self.assertRaises(ValueError):
            HttpControlPlaneLegalActorAssessor(
                "http://evil.example", lambda: "x", lambda: "c")

    def test_no_upstream_result_fails_closed_before_native_erp_mutation(self):
        operation = LegalActorOperation(
            context_id=REQUEST["context_id"], tenant_id="tn-synthetic",
            operating_organisation_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
            expected_legal_entity_id="LE-VERIFIED",
            role="INVOICE_ISSUER", activity=REQUEST["activity"],
            market="ZA", capability=REQUEST["capability"],
            operation_reference=REQUEST["operation_reference"],
        )
        class MissingProvider:
            def ensure_legal_actor_usable(self, *_):
                raise AssertionError("unverified CP response reached native provider")
        touched = []
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                operation, assessor=self.client(Opener(result())),
                provider=MissingProvider(), execute=lambda: touched.append("posted"),
                now=lambda: datetime(2026, 10, 9, 14, tzinfo=timezone.utc))
        self.assertEqual(touched, [])


if __name__ == "__main__":
    unittest.main()
