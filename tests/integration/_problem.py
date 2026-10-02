"""Structural check of an RFC 9457 problem document against contracts/errors/v1/problem-details.schema.json.

A stand-in for validating against the pinned Shared schema (ERP-COMPAT-06 replaces it): required
members, closed member set, code grammar, UUID correlation id, status range."""

import re
import uuid

REQUIRED = {"type", "title", "status", "code", "correlation_id", "retryable"}
ALLOWED = REQUIRED | {"detail", "instance", "trace_id", "errors"}
CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")


def check_problem(test, status, headers, body, *, expected_status, code, flat=False):
    test.assertEqual(status, expected_status, body)
    test.assertEqual(headers.get("Content-Type"), "application/problem+json")
    test.assertTrue(REQUIRED <= set(body), f"missing {REQUIRED - set(body)}: {body}")
    test.assertLessEqual(set(body), ALLOWED, f"unexpected members: {set(body) - ALLOWED}")
    test.assertEqual(body["status"], expected_status)
    test.assertEqual(body["code"], code)
    test.assertRegex(body["code"], CODE)
    test.assertTrue(body["title"] and len(body["title"]) <= 120)
    test.assertIsInstance(body["retryable"], bool)
    test.assertRegex(body["type"], r"^https://")
    uuid.UUID(body["correlation_id"])
    test.assertEqual(body["correlation_id"], headers.get("X-Correlation-ID"))
    if "trace_id" in body:
        test.assertRegex(body["trace_id"], r"^(?!0{32})[0-9a-f]{32}$")
    if "detail" in body:
        test.assertLessEqual(len(body["detail"]), 2048)
    if flat:  # the iDempiere-side client parses flat JSON only
        test.assertTrue(all(not isinstance(v, (dict, list)) for v in body.values()), body)
    test.assertNotIn("error", body)
