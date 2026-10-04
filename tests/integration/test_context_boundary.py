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
from security.platform_context import ContextRejected, ContextUnavailable

CONTEXT = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b"
ISSUER = "https://iam.example.invalid"
TENANT = "tn_01k4zuribeans"


class ContextBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.calls = []
        self.rejection = None
        test = self

        class Keys:
            def resolve(self, token):
                return test.key.public_key()

        class Validator:
            def validate(self, **kwargs):
                test.calls.append(kwargs)
                if test.rejection:
                    raise test.rejection
                return TENANT

        self.config = SimpleNamespace(
            database_url="never-connect", workload_oidc_issuer=ISSUER, workload_oidc_audience="baobab-erp",
            provisioning=None, context_validator=Validator())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.config, key_resolver=Keys()))
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def token(self, tenant=None):
        claims = {"iss": ISSUER, "aud": "baobab-erp", "sub": "svc", "azp": "svc", "actor_type": "workload",
                  "scope": "erp:read erp:provision", "exp": int(time.time()) + 300}
        if tenant is not None:
            claims["tenant_id"] = tenant
        return jwt.encode(claims, self.key, algorithm="RS256")

    def call(self, method, path, *, token=None, context=CONTEXT, body_tenant=TENANT):
        token = token or self.token()
        data = None
        if method == "POST":
            data = json.dumps({"context_id": context, "tenant_id": body_tenant}).encode()
        elif context is not None:
            path += "?context_id=" + context
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data, method=method,
            headers={"Authorization": "Bearer " + token, "Idempotency-Key": "idem-0123456789abcdef"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
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

    def test_cp_outage_is_retryable_and_mapping_reads_still_require_token_tenant(self):
        self.rejection = ContextUnavailable()
        with patch("application.server.psycopg.connect") as database:
            status, body = self.call("GET", "/inventory-availability")
            self.assertEqual((status, body["retryable"]), (503, True))
            self.assertEqual(self.call("GET", "/mappings", context=None)[0], 403)
            database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
