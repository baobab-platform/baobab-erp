"""Live HTTP responses from ERP's real server, checked against the pinned Shared contracts: the Boundary API's
OpenAPI response schemas (erp/v1/openapi.yaml) and RFC 9457 problem documents (errors/v1/problem-details).

Needs DATABASE_URL (a migrated Postgres), like the integration suite."""

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
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

import _shared as shared
from application.problem import kind_for_status, problem
from mapping.postgres_store import PostgresCanonicalMappingStore

ISSUER = "https://iam.example.invalid/realms/baobab"
PROBLEM = shared.schema_uri("errors/v1/problem-details.schema.json")
# Statuses ERP returns that the pinned OpenAPI does not declare for the operation. Each is a problem+json
# and is tracked as a Shared contract gap (declare 400 on the mapping reads; declare 501 for operations
# whose backing capability is not available), never silently accepted.
KNOWN_UNDECLARED = {
    ("GET", "/mappings/{mapping_id}", 400),
    ("GET", "/mappings", 400),
    ("GET", "/order-consequences/{commerce_order_id}", 501),
    ("GET", "/inventory-availability", 501),
    ("GET", "/provisioning-operations/{operation_id}", 501),
    ("POST", "/provisioning-operations", 501),
}


class _Key:
    def __init__(self, key):
        self._key = key

    def resolve(self, token):
        return self._key


class HttpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL must point at a migrated Postgres; the conformance suite never skips silently")
        os.environ.setdefault("BAOBAB_EVENT_SIGNING_SECRET", "conformance-secret")
        os.environ["BAOBAB_IAM_OIDC_ISSUER"] = ISSUER
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        from application.server import Config, make_handler

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Config(), key_resolver=_Key(cls.key.public_key())))
        cls.port = cls.server.server_address[1]
        Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tenant = f"tn_{uuid.uuid4().hex[:16]}"
        self.other = f"tn_{uuid.uuid4().hex[:16]}"
        self.connection = psycopg.connect(os.environ["DATABASE_URL"])
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.entity_mapping WHERE tenant_id = ANY(%s)", ([self.tenant, self.other],))
        self.connection.commit()
        self.connection.close()

    def _token(self, scope="erp:read", tenant="default"):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": "baobab-erp", "sub": "svc", "azp": "svc", "actor_type": "workload",
                  "scope": scope, "iat": now, "exp": now + 300}
        tenant = self.tenant if tenant == "default" else tenant
        if tenant:
            claims["tenant_id"] = tenant
        return jwt.encode(claims, self.key, algorithm="RS256")

    def _call(self, method, path, token="default"):
        headers = {}
        token = self._token() if token == "default" else token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read())

    def _mapping(self, tenant=None, owner="trade", resource_type="customer"):
        canonical_id = str(uuid.uuid4())
        mapping_id = PostgresCanonicalMappingStore(self.connection).create_mapping(
            tenant or self.tenant, "ZURIBEANS-ZA", resource_type, canonical_id, "C_BPartner",
            uuid.uuid4().int % 2_000_000_000, canonical_owner=owner)
        self.connection.commit()
        return mapping_id, canonical_id

    def assert_contract(self, method, template, result):
        status, headers, body = result
        content_type = headers["Content-Type"]
        declared = shared.declared_statuses(template, method)
        if status in declared:
            self.assertIn(content_type, shared.declared_media(template, method, status), (status, content_type))
            self.assertEqual(shared.errors_for(template, method, status, content_type, body), [], body)
        else:
            self.assertIn((method, template, status), KNOWN_UNDECLARED, f"{method} {template} returned undeclared {status}")
            self.assertEqual(content_type, "application/problem+json")
            self.assertEqual(shared.errors(PROBLEM, body), [], body)
        return status, headers, body

    # -- success responses are exactly the declared schemas
    def test_get_mapping_matches_the_declared_200_schema(self):
        mapping_id, canonical_id = self._mapping()
        status, _, body = self.assert_contract("GET", "/mappings/{mapping_id}", self._call("GET", f"/mappings/{mapping_id}"))
        self.assertEqual(status, 200)
        self.assertEqual(body["canonical_reference"]["resource_id"], canonical_id)

    def test_find_mappings_matches_the_declared_collection_schema(self):
        _, canonical_id = self._mapping()
        path = f"/mappings?owner=trade&resource_type=customer&resource_id={canonical_id}"
        status, _, body = self.assert_contract("GET", "/mappings", self._call("GET", path))
        self.assertEqual((status, len(body["items"])), (200, 1))
        status, _, body = self.assert_contract(
            "GET", "/mappings", self._call("GET", f"/mappings?owner=trade&resource_type=customer&resource_id={uuid.uuid4()}"))
        self.assertEqual((status, body), (200, {"items": []}))

    # -- error responses are problem documents, declared or tracked
    def test_every_error_the_mapping_reads_can_return_conforms(self):
        mapping_id, _ = self._mapping(tenant=self.other)
        cases = [
            ("/mappings/{mapping_id}", f"/mappings/{mapping_id}", dict(), 404),
            ("/mappings/{mapping_id}", "/mappings/nope", dict(), 400),
            ("/mappings/{mapping_id}", f"/mappings/{mapping_id}", dict(token=None), 401),
            ("/mappings/{mapping_id}", f"/mappings/{mapping_id}", dict(token=self._token(scope="erp:integrate")), 403),
            ("/mappings/{mapping_id}", f"/mappings/{mapping_id}", dict(token=self._token(tenant=None)), 403),
            ("/mappings", "/mappings?owner=bogus&resource_type=customer&resource_id=abc123", dict(), 400),
            ("/mappings", "/mappings?owner=trade&resource_type=customer&resource_id=abc123", dict(token=None), 401),
            ("/mappings", "/mappings?owner=trade&resource_type=customer&resource_id=abc123",
             dict(token=self._token(scope="x:y")), 403),
        ]
        for template, path, kwargs, expected in cases:
            with self.subTest(path=path, expected=expected):
                status, *_ = self.assert_contract("GET", template, self._call("GET", path, **kwargs))
                self.assertEqual(status, expected)

    def test_unimplemented_operations_answer_tracked_501_problem_documents(self):
        for method, template, path in [
            ("GET", "/order-consequences/{commerce_order_id}", "/order-consequences/ord-1"),
            ("GET", "/inventory-availability", "/inventory-availability?sku_id=s-1&warehouse_id=erp_abcdef12"),
            ("GET", "/provisioning-operations/{operation_id}", "/provisioning-operations/op_abcdef12"),
            ("POST", "/provisioning-operations", "/provisioning-operations"),
        ]:
            with self.subTest(template):
                scope = "erp:provision" if method == "POST" else "erp:read"
                status, *_ = self.assert_contract(method, template, self._call(method, path, token=self._token(scope=scope, tenant=None)))
                self.assertEqual(status, 501)

    def test_known_undeclared_statuses_are_really_undeclared(self):
        """Keeps the tracking list honest: when Shared declares one, it must leave this list."""
        for method, template, status in KNOWN_UNDECLARED:
            self.assertNotIn(status, shared.declared_statuses(template, method), (method, template, status))

    def test_every_implemented_operation_path_exists_in_the_contract(self):
        for template in ("/mappings/{mapping_id}", "/mappings"):
            self.assertIn(template, shared._OPENAPI["paths"])

    # -- legacy routes use the same problem contract
    def test_legacy_route_errors_validate_against_the_problem_schema(self):
        integrate = self._token(scope="erp:integrate")
        for status, path, token in [(401, "/mapping/resolve", None), (404, "/nope", None),
                                    (400, "/mapping/resolve", integrate), (403, "/mapping/resolve", self._token(scope="x:y"))]:
            with self.subTest(path=path, status=status):
                got, headers, body = self._call("GET", path, token=token)
                self.assertEqual(got, status)
                self.assertEqual(headers["Content-Type"], "application/problem+json")
                self.assertEqual(shared.errors(PROBLEM, body), [], body)

    def test_every_problem_kind_validates(self):
        for status in (400, 401, 403, 404, 500, 501, 502, 503):
            _, body = problem(kind_for_status(status), correlation_id=str(uuid.uuid4()),
                              trace_id="0af7651916cd43dd8448eb211c80319c", detail="x")
            self.assertEqual(shared.errors(PROBLEM, body), [], status)


if __name__ == "__main__":
    unittest.main()
