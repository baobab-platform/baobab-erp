"""LA-05D4: documentary negative-only evidence cannot authorize ERP mutation."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import Mock

from order_to_cash.documentary_restriction import (
    HttpControlPlaneDocumentaryRestrictionAssessor,
    assert_documentary_scope_unblocked,
)
from order_to_cash.legal_actor_gate import LegalActorNotAuthorised, LegalActorOperation

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
OP = LegalActorOperation(
    context_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
    tenant_id="tn_synthetic", operating_organisation_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
    expected_legal_entity_id="LE-SYNTHETIC", role="INVOICE_ISSUER",
    activity="B2B_INVOICE", market="ZA", capability="accounting.customer-invoice.post",
    operation_reference="synthetic-invoice-123",
)


def clear():
    return {
        "context_id": OP.context_id, "organisation_id": OP.operating_organisation_id,
        "market": OP.market, "capability": OP.capability,
        "operation_reference": OP.operation_reference,
        "blocked": False, "authority_granted": False,
        "policy_reference": "ADR-BCP-026/PEO-02T:negative-only",
        "evaluated_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(seconds=1)).isoformat(),
    }


class Response:
    status = 200

    def __init__(self, data):
        self.data = BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        return self.data.read(size)


class TestERPDocumentaryNegativeVeto(unittest.TestCase):
    def test_exact_current_clear_scope_is_only_nonblocking_not_permission(self):
        self.assertIsNone(assert_documentary_scope_unblocked(OP, clear(), now=NOW))
        for altered in (
            {"blocked": True}, {"blocked": "false"}, {"authority_granted": True},
            {"organisation_id": "wrong-org"}, {"context_id": "wrong-context"},
            {"capability": "payments.capture"}, {"market": "UG"},
            {"operation_reference": "another-invoice"}, {"policy_reference": "untrusted"},
            {"expires_at": (NOW - timedelta(seconds=1)).isoformat()},
            {"expires_at": (NOW + timedelta(seconds=30)).isoformat()},
            {"evaluated_at": (NOW - timedelta(seconds=30)).isoformat()},
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(LegalActorNotAuthorised):
                    assert_documentary_scope_unblocked(OP, {**clear(), **altered}, now=NOW)

    def test_authenticated_private_transport_does_not_trust_browser_or_stale_response(self):
        calls = []

        def opener(req, timeout):
            calls.append((req, timeout))
            return Response(json.dumps(clear()).encode())

        client = HttpControlPlaneDocumentaryRestrictionAssessor(
            "https://cp.example.test", token_provider=lambda: "iam-workload-token",
            correlation_provider=lambda: "synthetic-correlation", opener=Mock(open=opener),
        )
        request = {
            "context_id": OP.context_id, "market": OP.market,
            "capability": OP.capability, "operation_reference": OP.operation_reference,
        }
        self.assertEqual(client.assess(request), clear())
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].full_url.endswith("/internal/documentary/v1/restrictions/assess"))
        self.assertEqual(calls[0][0].get_header("Authorization"), "Bearer iam-workload-token")
        self.assertEqual(calls[0][0].get_header("Cache-control"), "no-store")
        with self.assertRaises(ValueError):
            HttpControlPlaneDocumentaryRestrictionAssessor(
                "http://untrusted.example", lambda: "token", lambda: "correlation",
            )

    def test_duplicate_json_keys_are_not_authoritative(self):
        client = HttpControlPlaneDocumentaryRestrictionAssessor(
            "https://cp.example.test", token_provider=lambda: "iam-workload-token",
            correlation_provider=lambda: "synthetic-correlation",
            opener=Mock(open=lambda req, timeout: Response(
                b'{"blocked":false,"blocked":true}'
            )),
        )
        with self.assertRaises(LegalActorNotAuthorised):
            client.assess({
                "context_id": OP.context_id, "market": OP.market,
                "capability": OP.capability, "operation_reference": OP.operation_reference,
            })


if __name__ == "__main__":
    unittest.main()
