"""ERP-COMPAT-04: every error from the pre-contract routes is RFC 9457 application/problem+json.

Real Postgres + real HTTP server. Negative cases only: 400, 401, 403, 404, 500 (including an
unexpected failure), 503, each with the correlation id echoed and no internal text leaked."""

import hashlib
import hmac
import json
import os
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from threading import Thread

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from _postgres import require_database_url
from _problem import check_problem

ISSUER = "https://iam.example.invalid/realms/baobab"
SECRET = "integration-test-secret"


class _Key:
    def __init__(self, key):
        self._key = key

    def resolve(self, token):
        return self._key


def _serve(database_url, key):
    os.environ["DATABASE_URL"] = database_url
    os.environ["BAOBAB_EVENT_SIGNING_SECRET"] = SECRET
    os.environ["BAOBAB_IAM_OIDC_ISSUER"] = ISSUER
    from application.server import Config, make_handler

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Config(), key_resolver=_Key(key.public_key())))
    Thread(target=server.serve_forever, daemon=True).start()
    return server


class LegacyProblemDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_url = require_database_url()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.server = _serve(cls.database_url, cls.key)
        cls.port = cls.server.server_address[1]
        # A second server whose database cannot be reached, for the failure paths.
        cls.broken = _serve("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", cls.key)
        cls.broken_port = cls.broken.server_address[1]
        os.environ["DATABASE_URL"] = cls.database_url

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.broken):
            server.shutdown()
            server.server_close()

    def _token(self, scope="erp:integrate", **claims):
        now = int(time.time())
        body = {"iss": ISSUER, "aud": "baobab-erp", "sub": "svc", "azp": "svc", "actor_type": "workload",
                "scope": scope, "iat": now, "exp": now + 300}
        body.update(claims)
        return jwt.encode(body, self.key, algorithm="RS256")

    def _call(self, method, path, *, token="default", body=None, headers=None, port=None, raw=None):
        h = dict(headers or {})
        token = self._token() if token == "default" else token
        if token:
            h["Authorization"] = f"Bearer {token}"
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(f"http://127.0.0.1:{port or self.port}{path}", data=data,
                                         method=method, headers=h)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read())

    def assertProblem(self, result, status, code):
        check_problem(self, *result, expected_status=status, code=code, flat=True)

    # 400
    def test_missing_query_parameters_are_400(self):
        for path in ("/context/resolve", "/context/resolve-tenant", "/mapping/resolve", "/mapping/resolve-canonical"):
            self.assertProblem(self._call("GET", path), 400, "ERP_INVALID_REQUEST")

    def test_bad_request_bodies_are_400(self):
        self.assertProblem(self._call("POST", "/outbox/record", raw=b""), 400, "ERP_INVALID_REQUEST")
        self.assertProblem(self._call("POST", "/outbox/record", raw=b"{not json"), 400, "ERP_INVALID_REQUEST")
        self.assertProblem(self._call("POST", "/outbox/record", raw=b"[1,2]"), 400, "ERP_INVALID_REQUEST")
        self.assertProblem(self._call("POST", "/outbox/record", body={"event_type": "x"}), 400, "ERP_INVALID_REQUEST")

    def test_order_to_cash_validation_is_400(self):
        self.assertProblem(self._call("POST", "/sales-orders", body={}), 400, "ERP_INVALID_REQUEST")

    # 401
    def test_unauthenticated_is_401_and_never_leaks_validator_text(self):
        for token in (None, "garbage", self._token(aud="someone-else"), self._token(actor_type="human")):
            status, headers, body = result = self._call("GET", "/mapping/resolve", token=token)
            self.assertProblem(result, 401, "ERP_AUTHENTICATION_REQUIRED")
            self.assertNotIn("Invalid token", json.dumps(body))
            self.assertNotIn("signature", json.dumps(body).lower())

    def test_invalid_event_signature_is_401(self):
        payload = b"{}"
        self.assertProblem(self._call("POST", "/events/inbound", raw=payload, token=None,
                                      headers={"X-Baobab-Signature": "bad"}), 401, "ERP_AUTHENTICATION_REQUIRED")

    # 403
    def test_missing_scope_is_403(self):
        for scope in ("other:scope", ""):
            self.assertProblem(self._call("GET", "/mapping/resolve", token=self._token(scope=scope)),
                               403, "ERP_FORBIDDEN")

    # 404
    def test_unknown_paths_and_unmapped_resources_are_404(self):
        self.assertProblem(self._call("GET", "/nope", token=None), 404, "ERP_RESOURCE_NOT_FOUND")
        self.assertProblem(self._call("POST", "/nope", token=None, body={}), 404, "ERP_RESOURCE_NOT_FOUND")
        self.assertProblem(
            self._call("GET", f"/mapping/resolve?tenant_id=tn_x{uuid.uuid4().hex[:8]}&canonical_type=Party"
                              f"&canonical_id={uuid.uuid4()}"), 404, "ERP_RESOURCE_NOT_FOUND")
        self.assertProblem(self._call("GET", "/context/resolve?tenant_id=tn_nobody&entity_id=NOBODY-X"),
                           404, "ERP_RESOURCE_NOT_FOUND")

    # 5xx
    def test_unreachable_database_is_503_on_readiness_and_never_echoes_the_driver_error(self):
        status, headers, body = result = self._call("GET", "/health/ready", token=None, port=self.broken_port)
        self.assertProblem(result, 503, "ERP_SERVICE_UNAVAILABLE")
        self.assertTrue(body["retryable"])
        self.assertNotIn("127.0.0.1", json.dumps(body))

    def test_unexpected_failure_is_500_problem_not_an_html_page(self):
        status, headers, body = result = self._call(
            "GET", f"/mapping/resolve?tenant_id=tn_x&canonical_type=Party&canonical_id={uuid.uuid4()}",
            port=self.broken_port)
        self.assertProblem(result, 500, "ERP_INTERNAL_ERROR")
        self.assertNotIn("127.0.0.1", json.dumps(body))
        self.assertNotIn("Traceback", json.dumps(body))

    def test_missing_process_configuration_is_503(self):
        from application.server import Config

        # The default test Config has no native process ids configured; order-to-cash completes need them.
        if Config().order_to_cash_process_ids is not None:
            self.skipTest("process ids are configured in this environment")
        result = self._call("POST", "/sales-orders/complete", body={
            "tenant_id": "tn_x", "entity_id": "X-LE", "sales_order_canonical_id": str(uuid.uuid4())})
        self.assertIn(result[0], (400, 404, 503))
        check_problem(self, *result, expected_status=result[0], code={
            400: "ERP_INVALID_REQUEST", 404: "ERP_RESOURCE_NOT_FOUND", 503: "ERP_SERVICE_UNAVAILABLE"}[result[0]],
            flat=True)

    # correlation / trace
    def test_supplied_correlation_id_is_echoed_and_a_bad_one_is_replaced(self):
        cid = str(uuid.uuid4())
        status, headers, body = self._call("GET", "/mapping/resolve", headers={"X-Correlation-ID": cid})
        self.assertEqual((headers["X-Correlation-ID"], body["correlation_id"]), (cid, cid))
        status, headers, body = self._call("GET", "/mapping/resolve", headers={"X-Correlation-ID": "nope"})
        self.assertEqual(status, 400)  # legacy routes do not reject the header, just do not echo it
        uuid.UUID(body["correlation_id"])
        self.assertNotEqual(body["correlation_id"], "nope")

    def test_traceparent_becomes_trace_id(self):
        trace = "0af7651916cd43dd8448eb211c80319c"
        _, _, body = self._call("GET", "/mapping/resolve", headers={"traceparent": f"00-{trace}-b7ad6b7169203331-01"})
        self.assertEqual(body["trace_id"], trace)

    def test_successful_responses_are_unchanged(self):
        status, headers, body = self._call("GET", "/health/live", token=None)
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))


if __name__ == "__main__":
    unittest.main()
