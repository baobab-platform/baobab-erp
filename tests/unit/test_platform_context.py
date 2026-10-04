"""CP delegation cannot become local tenant authority or leak caller credentials."""
import io
import json
import unittest
import urllib.error
from datetime import datetime, timezone

from security.platform_context import (
    ContextRejected, ContextUnavailable, HttpContextValidator, InvalidContext,
    request_context_id, validated_tenant,
)

CONTEXT = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b"
NOW = datetime(2026, 10, 4, 5, tzinfo=timezone.utc)
ANSWER = {"context_id": CONTEXT, "tenant_id": "tn_01k4zuribeans",
          "resolved_at": "2026-10-04T04:00:00Z", "expires_at": "2026-10-04T06:00:00Z"}


class ContextTests(unittest.TestCase):
    def test_missing_duplicate_and_noncanonical_context_are_invalid(self):
        for query in ("", "context_id=", "context_id=nope", f"context_id={CONTEXT}&context_id={CONTEXT}"):
            with self.subTest(query), self.assertRaises(InvalidContext):
                request_context_id("GET", b"", query)
        for body in (b"[]", b"{}", b"{", json.dumps({"context_id": " " + CONTEXT}).encode(),
                     f'{{"context_id":"{CONTEXT}","context_id":"{CONTEXT}"}}'.encode()):
            with self.subTest(body), self.assertRaises(InvalidContext):
                request_context_id("POST", body, "")

    def test_response_needs_bounded_current_authority_and_exact_requested_context(self):
        self.assertEqual(validated_tenant(ANSWER, CONTEXT, now=NOW), ANSWER["tenant_id"])
        for patch in ({"expires_at": None}, {"expires_at": "bad"}, {"expires_at": "2026-10-04T06:00:00"},
                      {"context_id": "other"}, {"tenant_id": "tenant-local"}, {"legal_entity_id": "ZURIBEANS-ZA"},
                      {"organisation_type": "invented"}):
            with self.subTest(patch), self.assertRaises(ContextUnavailable):
                validated_tenant(dict(ANSWER, **patch), CONTEXT, now=NOW)
        for expiry in ("2026-10-04T05:00:00Z", "2026-10-04T03:00:00Z"):
            with self.assertRaises(ContextRejected):
                validated_tenant(dict(ANSWER, expires_at=expiry), CONTEXT, now=NOW)
        for field in ANSWER:
            with self.assertRaises(ContextUnavailable):
                validated_tenant({k: v for k, v in ANSWER.items() if k != field}, CONTEXT, now=NOW)

    def test_cp_request_separates_validator_authentication_from_actual_subject_token(self):
        seen = []

        class Response(io.BytesIO):
            status = 200

        class Opener:
            def open(self, request, *, timeout):
                seen.append(request)
                return Response(json.dumps(dict(ANSWER, resolved_at="2020-01-01T00:00:00Z",
                                                expires_at="2099-01-01T00:00:00Z")).encode())

        validator = HttpContextValidator("https://cp.example.invalid", lambda: "erp-validator-token", opener=Opener())
        tenant = validator.validate(context_id=CONTEXT, subject_token="actual-incoming-token", correlation_id=CONTEXT)
        self.assertEqual(tenant, ANSWER["tenant_id"])
        self.assertEqual(seen[0].full_url, "https://cp.example.invalid/v1/platform-context/validate")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer erp-validator-token")
        self.assertEqual(json.loads(seen[0].data), {"context_id": CONTEXT, "subject_token": "actual-incoming-token"})

    def test_all_authority_refusals_are_indistinguishable_and_outages_stay_unavailable(self):
        for status in (400, 401, 403, 404, 409, 410, 500, 503):
            class Opener:
                def open(self, request, *, timeout):
                    raise urllib.error.HTTPError(request.full_url, status, "private detail", {}, None)
            validator = HttpContextValidator("https://cp.example.invalid", lambda: "erp-token", opener=Opener())
            with self.subTest(status), self.assertRaises(ContextRejected if status < 500 else ContextUnavailable):
                validator.validate(context_id=CONTEXT, subject_token="subject", correlation_id=CONTEXT)


if __name__ == "__main__":
    unittest.main()
