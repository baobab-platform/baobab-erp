"""Real HTTP boundary: rejected context must precede every database or replay access."""
import json
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from application.server import make_handler
from security.platform_context import (ContextRejected, ContextUnavailable, ProvisioningAuthority, RUNTIME, TENANT_PROVISIONING,
                                       ValidatedContext)

CONTEXT = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b"
ISSUER = "https://iam.example.invalid"
TENANT = "tn_01k4zuribeans"
PLAN = ("tp_01k4zuribeans", "plan_01k4zuribeans", 2, "sha256:" + "ab" * 32)
PROVISIONING_PATHS = ("/provisioning-operations",)


class ContextBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.calls = []
        self.rejection = None
        self.default_answer = (RUNTIME, None)
        self.answer = None  # (purpose, plan tuple) the Control Plane says the context is authority for; None = what the route needs
        test = self

        class Keys:
            def resolve(self, token):
                return test.key.public_key()

        class Validator:
            def validate(self, **kwargs):
                test.calls.append(kwargs)
                if test.rejection:
                    raise test.rejection
                purpose, plan = test.answer if test.answer is not None else test.default_answer
                return ValidatedContext(TENANT, purpose, ProvisioningAuthority(*plan) if plan else None)

        self.validator = Validator()
        self.config = SimpleNamespace(
            database_url="never-connect", workload_oidc_issuer=ISSUER, workload_oidc_audience="baobab-erp",
            provisioning=None, context_validator=self.validator)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.config, key_resolver=Keys()))
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def token(self, tenant=None, scope="erp:read erp:provision"):
        claims = {"iss": ISSUER, "aud": "baobab-erp", "sub": "svc", "azp": "svc", "actor_type": "workload",
                  "scope": scope, "exp": int(time.time()) + 300}
        if tenant is not None:
            claims["tenant_id"] = tenant
        return jwt.encode(claims, self.key, algorithm="RS256")

    def call(self, method, path, *, token=None, context=CONTEXT, body_tenant=TENANT, authority=PLAN):
        token = token or self.token()
        data = None
        # What a Control Plane context for this route is authority FOR, unless a test says otherwise.
        self.default_answer = (TENANT_PROVISIONING, PLAN) if path.startswith(PROVISIONING_PATHS) else (RUNTIME, None)
        if method == "POST":
            body = {"context_id": context, "tenant_id": body_tenant}
            if authority is not None:
                body["control_plane_authority"] = dict(zip(("tenant_provisioning_id", "plan_id", "plan_version", "plan_digest"), authority))
            data = json.dumps(body).encode()
        elif context is not None:
            path += "?context_id=" + context
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data, method=method,
            headers={"Authorization": "Bearer " + token, "Idempotency-Key": "idem-0123456789abcdef"})
        try:
            with urllib.request.urlopen(request) as response:
                self.last_headers = response.headers
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            self.last_headers = exc.headers
            return exc.code, json.loads(exc.read())

    def test_rejected_authority_blocks_all_four_operations_before_database_or_replay_reads(self):
        self.rejection = ContextRejected()
        paths = [("POST", "/provisioning-operations"), ("GET", "/provisioning-operations/" + CONTEXT),
                 ("GET", "/order-consequences/order-1"), ("GET", "/inventory-availability")]
        with patch("application.server.psycopg.connect") as database:
            for method, path in paths:
                with self.subTest(path):
                    status, body = self.call(method, path)
                    self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
            database.assert_not_called()

    def test_missing_context_and_unavailable_validator_cannot_use_token_tenant_as_fallback(self):
        with patch("application.server.psycopg.connect") as database:
            self.assertEqual(self.call("GET", "/inventory-availability", context=None, token=self.token(TENANT))[0], 400)
            self.config.context_validator = None
            self.assertEqual(self.call("GET", "/inventory-availability", token=self.token(TENANT))[0], 503)
            database.assert_not_called()

    def test_actual_bearer_is_forwarded_and_tenant_disagreements_do_not_reach_storage(self):
        token = self.token("tn_other123")
        with patch("application.server.psycopg.connect") as database:
            status, body = self.call("GET", "/inventory-availability", token=token)
            self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
            self.assertEqual(self.calls[-1]["subject_token"], token)
            status, body = self.call("POST", "/provisioning-operations", body_tenant="tn_other123")
            self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
            database.assert_not_called()

    def test_a_malformed_tenant_is_an_invalid_request_not_a_rejected_context(self):
        # Only a different WELL-FORMED tenant disagrees with the context's authority; anything else is a bad document.
        with patch("application.server.psycopg.connect") as database:
            for bad in ("bad", "TN_upper", "tn_" + "a" * 61, "tn_01k4zuribeans\n", ""):
                with self.subTest(bad):
                    status, body = self.call("POST", "/provisioning-operations", body_tenant=bad)
                    self.assertEqual((status, body["code"]), (400, "ERP_INVALID_REQUEST"), body)
            status, body = self.call("POST", "/provisioning-operations", body_tenant="tn_other123")
            self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
            database.assert_not_called()

    def test_cp_outage_is_retryable_and_mapping_reads_still_require_token_tenant(self):
        self.rejection = ContextUnavailable()
        with patch("application.server.psycopg.connect") as database:
            status, body = self.call("GET", "/inventory-availability")
            self.assertEqual((status, body["retryable"]), (503, True))
            self.assertEqual(self.call("GET", "/mappings", context=None)[0], 403)
            database.assert_not_called()

    def _control_plane_unavailable(self):
        self.config.context_validator = self.validator  # configured again; the Control Plane is what is down
        self.rejection = ContextUnavailable()

    PATHS = [("POST", "/provisioning-operations"), ("GET", "/provisioning-operations/" + CONTEXT),
             ("GET", "/order-consequences/order-1"), ("GET", "/inventory-availability")]

    def test_every_unavailable_answer_on_the_context_path_carries_retry_after(self):
        # Shared erp/v1: the ServiceUnavailable response declares an integer Retry-After header.
        with patch("application.server.psycopg.connect") as database:
            for label, arrange in (("validator unconfigured", lambda: setattr(self.config, "context_validator", None)),
                                   ("control plane unavailable", self._control_plane_unavailable)):
                arrange()
                for method, path in self.PATHS:
                    with self.subTest(f"{label}: {path}"):
                        status, body = self.call(method, path)
                        self.assertEqual((status, body["code"]), (503, "ERP_SERVICE_UNAVAILABLE"))
                        self.assertTrue(self.last_headers["Retry-After"].isdigit(), self.last_headers)
            database.assert_not_called()

    def test_scope_is_checked_before_the_control_plane_is_asked(self):
        # Shared erp/v1 1.1.1: following a provisioning operation is erp:provision; erp:read is for business-data reads.
        self.rejection = ContextRejected()
        reader, provisioner = self.token(scope="erp:read"), self.token(scope="erp:provision")
        with patch("application.server.psycopg.connect") as database:
            status, body = self.call("GET", "/provisioning-operations/" + CONTEXT, token=reader)
            self.assertEqual((status, body["code"]), (403, "ERP_FORBIDDEN"))
            status, body = self.call("GET", "/order-consequences/order-1", token=provisioner)
            self.assertEqual((status, body["code"]), (403, "ERP_FORBIDDEN"))
            status, body = self.call("GET", "/inventory-availability", token=provisioner)
            self.assertEqual((status, body["code"]), (403, "ERP_FORBIDDEN"))
            self.assertEqual(self.calls, [], "a caller without the scope must not cause a Control Plane call")
            # With the right scope each reaches validation, which here refuses.
            for path, token in (("/provisioning-operations/" + CONTEXT, provisioner), ("/order-consequences/order-1", reader),
                                ("/inventory-availability", reader)):
                status, body = self.call("GET", path, token=token)
                self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"), path)
            self.assertEqual(len(self.calls), 3)
            database.assert_not_called()

    def test_a_context_is_authority_only_for_the_purpose_the_route_needs(self):
        # Shared erp/v1 1.2.0: provisioning accepts only a TENANT_PROVISIONING context, every business-data read only RUNTIME.
        paths = [("POST", "/provisioning-operations", RUNTIME), ("GET", "/provisioning-operations/" + CONTEXT, RUNTIME),
                 ("GET", "/order-consequences/order-1", TENANT_PROVISIONING), ("GET", "/inventory-availability", TENANT_PROVISIONING)]
        with patch("application.server.psycopg.connect") as database:
            for method, path, wrong in paths:
                self.answer = (wrong, PLAN if wrong == TENANT_PROVISIONING else None)
                with self.subTest(path, answered=wrong):
                    status, body = self.call(method, path)
                    self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
            database.assert_not_called()

    def test_the_plan_a_request_names_must_be_the_plan_its_context_is_bound_to(self):
        names = ("tenant_provisioning_id", "plan_id", "plan_version", "plan_digest")
        other = {"tenant_provisioning_id": "tp_01k4zuribeansb", "plan_id": "plan_01k4zuribeansb", "plan_version": 3,
                 "plan_digest": "sha256:" + "cd" * 32}
        with patch("application.server.psycopg.connect") as database:
            for index, name in enumerate(names):
                bound = list(PLAN)
                bound[index] = other[name]
                self.answer = (TENANT_PROVISIONING, tuple(bound))
                with self.subTest(name):
                    status, body = self.call("POST", "/provisioning-operations")
                    self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
            self.answer = None
            database.assert_not_called()

    def test_a_malformed_plan_in_the_request_is_an_invalid_document_not_a_rejected_context(self):
        # Only a well-formed plan that differs from the context's is an authority disagreement; the request parser answers
        # anything else with the contract's 400, and nothing is provisioned.
        with patch("application.server.psycopg.connect") as database:
            status, body = self.call("POST", "/provisioning-operations", authority=None)
            self.assertEqual((status, body["code"]), (400, "ERP_INVALID_REQUEST"))
            # The parser rejects it before any statement runs: the connection is opened for the handler and never used.
            self.assertEqual(database.return_value.__enter__.return_value.cursor.call_count, 0)


if __name__ == "__main__":
    unittest.main()
