import hashlib
import hmac
import json
import os
import random
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from threading import Thread

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

from _postgres import require_database_url

SECRET = "integration-test-secret"
OIDC_ISSUER = "https://iam.example.invalid/realms/baobab"


class _FixedKeyResolver:
    """A SigningKeyResolver returning a fixed key, standing in for a real Baobab
    IAM JWKS fetch -- this test suite has no live IAM instance to fetch one from."""

    def __init__(self, key):
        self._key = key

    def resolve(self, token: str):
        return self._key


class HttpServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_url = require_database_url()  # skips the whole class if unset
        os.environ["DATABASE_URL"] = database_url
        os.environ["BAOBAB_EVENT_SIGNING_SECRET"] = SECRET
        os.environ["BAOBAB_IAM_OIDC_ISSUER"] = OIDC_ISSUER

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.workload_token = cls._mint_workload_token(private_key)
        cls.wrong_audience_token = cls._mint_workload_token(private_key, aud="baobab-control-plane")
        cls.wrong_scope_token = cls._mint_wrong_scope_token(private_key)
        cls.no_scope_token = cls._mint_no_scope_token(private_key)

        from application.server import Config, make_handler

        config = Config()
        handler = make_handler(config, key_resolver=_FixedKeyResolver(private_key.public_key()))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @staticmethod
    def _mint_workload_token(private_key, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": OIDC_ISSUER,
            "aud": "baobab-erp",
            "sub": "service-account-baobab-erp-workload",
            "azp": "baobab-erp-workload",
            "actor_type": "workload",
            "scope": "erp:integrate",
            "iat": now,
            "exp": now + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256")

    @classmethod
    def _mint_wrong_scope_token(cls, private_key) -> str:
        return cls._mint_workload_token(private_key, scope="some:other:scope")

    @classmethod
    def _mint_no_scope_token(cls, private_key) -> str:
        return cls._mint_workload_token(private_key, scope="")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str, authorization: str | None = None):
        headers = {"Authorization": authorization} if authorization else {}
        request = urllib.request.Request(self._url(path), headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _get_as_workload(self, path: str):
        return self._get(path, authorization=f"Bearer {self.workload_token}")

    def _post_event(self, body: bytes, signature: str):
        request = urllib.request.Request(
            self._url("/events/inbound"), data=body, method="POST", headers={"X-Baobab-Signature": signature}
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_liveness(self):
        status, body = self._get("/health/live")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_readiness_against_real_database(self):
        status, body = self._get("/health/ready")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ready")

    def test_unknown_path_is_404(self):
        status, _ = self._get("/nope")
        self.assertEqual(status, 404)

    def test_inbound_event_end_to_end(self):
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "event_type": "trade.order.accepted",
            "schema_version": "1.0",
            "occurred_at": "2026-09-06T12:00:00Z",
            "source": "baobab-trade",
            "correlation_id": "cor-1",
            "tenant_id": "tenant-1",
            "entity_id": "THAMANI-GLOBAL",
            "payload": {},
        }
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        try:
            status, response_body = self._post_event(body, signature)
            self.assertEqual(status, 200)
            self.assertEqual(response_body["event_id"], event_id)

            # duplicate delivery is accepted, not reprocessed
            status, response_body = self._post_event(body, signature)
            self.assertEqual(status, 200)
        finally:
            with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
                cursor.execute("DELETE FROM baobab.event_inbox WHERE event_id = %s::uuid", (event_id,))
                connection.commit()

    def test_invalid_signature_is_rejected(self):
        body = json.dumps({"event_id": "whatever"}).encode()
        status, body_json = self._post_event(body, "sha256=wrong")
        self.assertEqual(status, 401)

    def test_context_resolve_end_to_end(self):
        tenant_id = f"test-tenant-{uuid.uuid4()}"
        entity_id = f"test-entity-{uuid.uuid4()}"
        # A randomised ad_client_id: baobab.tenant_mapping has a unique index on
        # (ad_client_id, ad_org_id) WHERE status = 'active', so a fixed literal could
        # collide with another active row already present in the database.
        ad_client_id = random.randint(100000, 999999)
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tenant_id, entity_id, ad_client_id, 1),
                )
            connection.commit()
            try:
                status, body = self._get_as_workload(f"/context/resolve?tenant_id={tenant_id}&entity_id={entity_id}")
                self.assertEqual(status, 200)
                self.assertEqual(body, {"ad_client_id": ad_client_id, "ad_org_id": 1})

                status, _ = self._get_as_workload(f"/context/resolve?tenant_id={tenant_id}&entity_id=no-such-entity")
                self.assertEqual(status, 404)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s", (tenant_id,))
                connection.commit()

    def test_context_resolve_tenant_end_to_end(self):
        tenant_id = f"test-tenant-{uuid.uuid4()}"
        entity_id = f"test-entity-{uuid.uuid4()}"
        ad_client_id = random.randint(100000, 999999)
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tenant_id, entity_id, ad_client_id, 1),
                )
            connection.commit()
            try:
                status, body = self._get_as_workload(f"/context/resolve-tenant?ad_client_id={ad_client_id}&ad_org_id=1")
                self.assertEqual(status, 200)
                self.assertEqual(body, {"tenant_id": tenant_id, "entity_id": entity_id})

                status, _ = self._get_as_workload("/context/resolve-tenant?ad_client_id=888888&ad_org_id=999")
                self.assertEqual(status, 404)

                status, _ = self._get_as_workload("/context/resolve-tenant?ad_client_id=notanumber&ad_org_id=1")
                self.assertEqual(status, 400)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s", (tenant_id,))
                connection.commit()

    def test_mapping_resolve_end_to_end(self):
        tenant_id = f"test-tenant-{uuid.uuid4()}"
        canonical_id = str(uuid.uuid4())
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO baobab.entity_mapping
                        (tenant_id, canonical_type, canonical_id, native_table, native_id)
                    VALUES (%s, %s, %s::uuid, %s, %s)
                    """,
                    (tenant_id, "Party", canonical_id, "C_BPartner", 1001),
                )
            connection.commit()
            try:
                status, body = self._get_as_workload(
                    f"/mapping/resolve?tenant_id={tenant_id}&canonical_type=Party&canonical_id={canonical_id}"
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, {"table": "C_BPartner", "record_id": 1001})

                status, body = self._get_as_workload(
                    f"/mapping/resolve-canonical?tenant_id={tenant_id}&table=C_BPartner&record_id=1001"
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, {"canonical_id": canonical_id})

                status, _ = self._get_as_workload(f"/mapping/resolve-canonical?tenant_id={tenant_id}&table=C_BPartner&record_id=999999")
                self.assertEqual(status, 404)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM baobab.entity_mapping WHERE tenant_id = %s", (tenant_id,))
                connection.commit()

    def test_mapping_resolve_missing_params_is_400(self):
        status, _ = self._get_as_workload("/mapping/resolve?tenant_id=x")
        self.assertEqual(status, 400)

    def test_context_resolve_without_a_token_is_401(self):
        # ADR-0014 §111: network location alone must no longer be enough.
        status, _ = self._get("/context/resolve?tenant_id=x&entity_id=y")
        self.assertEqual(status, 401)

    def test_mapping_resolve_without_a_token_is_401(self):
        status, _ = self._get("/mapping/resolve?tenant_id=x&canonical_type=Party&canonical_id=y")
        self.assertEqual(status, 401)

    def test_context_resolve_with_wrong_audience_token_is_401(self):
        # A token scoped for baobab-control-plane (context:resolve) must not also
        # work against baobab-erp's own boundary (ADR-0007 §§24-25).
        status, _ = self._get(
            "/context/resolve?tenant_id=x&entity_id=y",
            authorization=f"Bearer {self.wrong_audience_token}",
        )
        self.assertEqual(status, 401)

    def test_context_resolve_with_malformed_authorization_header_is_401(self):
        status, _ = self._get("/context/resolve?tenant_id=x&entity_id=y", authorization="not-a-bearer-token")
        self.assertEqual(status, 401)

    def test_context_resolve_with_wrong_scope_token_is_403(self):
        # A real, validly-signed, correctly-audienced workload token that simply
        # doesn't carry erp:integrate must be refused, not just any authenticated
        # workload (ADR-ERP-010's "authenticates but doesn't authorize" gap).
        status, _ = self._get(
            "/context/resolve?tenant_id=x&entity_id=y",
            authorization=f"Bearer {self.wrong_scope_token}",
        )
        self.assertEqual(status, 403)

    def test_mapping_resolve_with_no_scope_token_is_403(self):
        status, _ = self._get(
            "/mapping/resolve?tenant_id=x&canonical_type=Party&canonical_id=y",
            authorization=f"Bearer {self.no_scope_token}",
        )
        self.assertEqual(status, 403)

    def test_context_resolve_tenant_with_wrong_scope_token_is_403(self):
        status, _ = self._get(
            "/context/resolve-tenant?ad_client_id=1&ad_org_id=1",
            authorization=f"Bearer {self.wrong_scope_token}",
        )
        self.assertEqual(status, 403)

    def test_mapping_resolve_canonical_with_wrong_scope_token_is_403(self):
        status, _ = self._get(
            "/mapping/resolve-canonical?tenant_id=x&table=C_BPartner&record_id=1",
            authorization=f"Bearer {self.wrong_scope_token}",
        )
        self.assertEqual(status, 403)

    def test_health_and_events_endpoints_need_no_workload_token(self):
        # Health probes and the signed-event webhook have their own, separate
        # trust mechanisms (liveness/readiness are unauthenticated by design;
        # /events/inbound is HMAC-signed) -- they must not be caught by the new
        # workload-token gate.
        status, _ = self._get("/health/live")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
