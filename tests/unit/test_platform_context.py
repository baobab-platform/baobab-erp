"""CP delegation cannot become local tenant authority or leak caller credentials."""
import http.client
import io
import json
import unittest
import urllib.error
from datetime import datetime, timezone

from security.platform_context import (
    ContextRejected, ContextUnavailable, HttpContextValidator, InvalidContext, ProvisioningAuthority, ValidatedContext,
    request_context_id, validated_context,
)

CONTEXT = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b"
NOW = datetime(2026, 10, 4, 5, tzinfo=timezone.utc)
ANSWER = {"context_id": CONTEXT, "tenant_id": "tn_01k4zuribeans", "authority_purpose": "RUNTIME",
          "resolved_at": "2026-10-04T04:00:00Z", "expires_at": "2026-10-04T06:00:00Z"}
PLAN = {"tenant_provisioning_id": "tp_01k4zuribeans", "plan_id": "plan_01k4zuribeans", "plan_version": 2,
        "plan_digest": "sha256:" + "ab" * 32}
PROVISIONING = dict(ANSWER, authority_purpose="TENANT_PROVISIONING", provisioning_authority=PLAN)


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
        self.assertEqual(validated_context(ANSWER, CONTEXT, now=NOW), ValidatedContext(ANSWER["tenant_id"], "RUNTIME", None))
        for patch in ({"expires_at": None}, {"expires_at": "bad"}, {"expires_at": "2026-10-04T06:00:00"},
                      {"context_id": "other"}, {"tenant_id": "tenant-local"}, {"legal_entity_id": "ZURIBEANS-ZA"},
                      {"organisation_type": "invented"}, {"authority_purpose": "PENDING"}, {"authority_purpose": None},
                      {"authority_purpose": ["RUNTIME"]}, {"provisioning_authority": PLAN}):
            with self.subTest(patch), self.assertRaises(ContextUnavailable):
                validated_context(dict(ANSWER, **patch), CONTEXT, now=NOW)
        for expiry in ("2026-10-04T05:00:00Z", "2026-10-04T03:00:00Z"):
            with self.assertRaises(ContextRejected):
                validated_context(dict(ANSWER, expires_at=expiry), CONTEXT, now=NOW)
        for field in ANSWER:
            with self.assertRaises(ContextUnavailable):
                validated_context({k: v for k, v in ANSWER.items() if k != field}, CONTEXT, now=NOW)

    def test_the_purpose_is_stated_and_a_provisioning_answer_carries_exactly_its_plan(self):
        self.assertEqual(validated_context(PROVISIONING, CONTEXT, now=NOW), ValidatedContext(
            "tn_01k4zuribeans", "TENANT_PROVISIONING", ProvisioningAuthority("tp_01k4zuribeans", "plan_01k4zuribeans", 2, PLAN["plan_digest"])))
        without = {k: v for k, v in ANSWER.items() if k != "authority_purpose"}
        bad_plans = [None, [], {}, dict(PLAN, approval_id="apd_x1y2z3"), {k: v for k, v in PLAN.items() if k != "plan_digest"},
                     dict(PLAN, plan_version=0), dict(PLAN, plan_version=True), dict(PLAN, plan_version="2"),
                     dict(PLAN, plan_digest="sha256:short"), dict(PLAN, plan_id="x"), dict(PLAN, tenant_provisioning_id="tp_"),
                     dict(PLAN, tenant_provisioning_id="TP_X")]
        for answer in [without] + [dict(PROVISIONING, provisioning_authority=plan) for plan in bad_plans] + [
                {k: v for k, v in PROVISIONING.items() if k != "provisioning_authority"},
                dict(PROVISIONING, market_id="mkt_za"), dict(PROVISIONING, organisation_id="org_1"),
                dict(ANSWER, provisioning_authority=None)]:
            with self.subTest(answer), self.assertRaises(ContextUnavailable):
                validated_context(answer, CONTEXT, now=NOW)

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
        validated = validator.validate(context_id=CONTEXT, subject_token="actual-incoming-token", correlation_id=CONTEXT)
        self.assertEqual(validated, ValidatedContext(ANSWER["tenant_id"], "RUNTIME", None))
        self.assertEqual(seen[0].full_url, "https://cp.example.invalid/v1/platform-context/validate")
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer erp-validator-token")
        self.assertEqual(json.loads(seen[0].data), {"context_id": CONTEXT, "subject_token": "actual-incoming-token"})

    @staticmethod
    def _answer(status, body):
        """What the Control Plane answers to a validate call, as urllib raises it."""
        class Opener:
            def open(self, request, *, timeout):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                raise urllib.error.HTTPError(request.full_url, status, "private detail", {}, io.BytesIO(raw))
        return HttpContextValidator("https://cp.example.invalid", lambda: "erp-token", opener=Opener())

    def _validate(self, validator):
        return validator.validate(context_id=CONTEXT, subject_token="subject", correlation_id=CONTEXT)

    def test_only_what_the_control_plane_says_about_the_caller_is_a_rejection(self):
        for status, code in ((401, "SUBJECT_TOKEN_INVALID"), (404, "CONTEXT_NOT_FOUND"), (403, "TENANT_CONTEXT_MISMATCH"),
                             (403, "TENANT_NOT_ACTIVE"), (400, "VALIDATION_FAILED"),
                             (403, "PROVISIONING_AUTHORITY_NOT_CURRENT")):
            with self.subTest(status=status, code=code), self.assertRaises(ContextRejected):
                self._validate(self._answer(status, {"code": code, "status": status}))

    def test_erps_own_validator_problems_are_never_reported_as_the_callers_fault(self):
        # A rejected validator credential, an unregistered validator or an outage would otherwise be told to every caller
        # as "your context was rejected"; they are ERP's to fix, so they stay unavailable and retryable.
        for status, body in (
                (401, {"code": "AUTH_TOKEN_REQUIRED"}), (403, {"code": "CONTEXT_VALIDATION_NOT_PERMITTED"}),
                (503, {"code": "CONTEXT_VALIDATION_UNAVAILABLE"}), (503, {"code": "CONTEXT_STORE_UNAVAILABLE"}),
                (500, {"code": "INTERNAL_ERROR"}), (502, b"<html>bad gateway</html>"), (404, b"not json"),
                (404, {"detail": "no code member"}), (403, {"code": 7}), (404, [])):
            with self.subTest(status=status, body=body), self.assertRaises(ContextUnavailable):
                self._validate(self._answer(status, body))

    def test_a_rejection_code_with_the_wrong_status_is_not_trusted(self):
        for status, code in ((403, "SUBJECT_TOKEN_INVALID"), (401, "CONTEXT_NOT_FOUND"), (404, "TENANT_NOT_ACTIVE"),
                             (500, "CONTEXT_NOT_FOUND"), (200, "CONTEXT_NOT_FOUND"), (404, "PROVISIONING_AUTHORITY_NOT_CURRENT"),
                             (503, "PROVISIONING_AUTHORITY_NOT_CURRENT")):
            with self.subTest(status=status, code=code), self.assertRaises(ContextUnavailable):
                self._validate(self._answer(status, {"code": code}))

    def test_a_body_the_control_plane_cuts_short_is_unavailable_not_an_unhandled_error(self):
        # http.client.IncompleteRead is an HTTPException, neither an OSError nor a ValueError.
        class TruncatedError(urllib.error.HTTPError):
            def read(self, *_):
                raise http.client.IncompleteRead(b'{"code":"CONTEXT_', 40)

        class TruncatedErrorOpener:
            def open(self, request, *, timeout):
                raise TruncatedError(request.full_url, 404, "x", {}, None)

        class TruncatedSuccess:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, *_):
                raise http.client.IncompleteRead(b'{"context_id":', 200)

        class TruncatedSuccessOpener:
            def open(self, request, *, timeout):
                return TruncatedSuccess()

        class BadStatusOpener:
            def open(self, request, *, timeout):
                raise http.client.BadStatusLine("garbage")

        for opener in (TruncatedErrorOpener(), TruncatedSuccessOpener(), BadStatusOpener()):
            with self.subTest(type(opener).__name__), self.assertRaises(ContextUnavailable):
                self._validate(HttpContextValidator("https://cp.example.invalid", lambda: "erp-token", opener=opener))

    def test_an_unreadable_or_oversized_error_body_is_unavailable(self):
        class Unreadable(urllib.error.HTTPError):
            def read(self, *_):
                raise OSError("connection reset")

        class Opener:
            def open(self, request, *, timeout):
                raise Unreadable(request.full_url, 404, "x", {}, None)

        with self.assertRaises(ContextUnavailable):
            self._validate(HttpContextValidator("https://cp.example.invalid", lambda: "erp-token", opener=Opener()))
        with self.assertRaises(ContextUnavailable):
            self._validate(self._answer(404, b'{"code":"CONTEXT_NOT_FOUND","pad":"' + b"x" * 70000 + b'"}'))


if __name__ == "__main__":
    unittest.main()
