"""ERP-COMPAT-03a: the contract-shaped Boundary API read surface (contracts/erp/v1/openapi.yaml).

Real Postgres + real HTTP server. Proves authentication/authorisation order, tenant isolation from the
token claim (never the request), RFC 9457 error shape, correlation handling, and that unimplemented
operations answer 501 problem+json instead of fabricating data.
"""

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

from _postgres import require_database_url
from mapping.postgres_store import PostgresCanonicalMappingStore

ISSUER = "https://iam.example.invalid/realms/baobab"
PROBLEM_REQUIRED = {"type", "title", "status", "code", "correlation_id", "retryable"}
MAPPING_REQUIRED = {"mapping_id", "tenant_id", "legal_entity_id", "canonical_reference", "erp_resource_id",
                    "status", "revision", "effective_from"}


class _Key:
    def __init__(self, key):
        self._key = key

    def resolve(self, token):
        return self._key


class BoundaryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = require_database_url()
        os.environ["BAOBAB_EVENT_SIGNING_SECRET"] = "s"
        os.environ["BAOBAB_IAM_OIDC_ISSUER"] = ISSUER
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        from application.server import Config, make_handler

        cls.config = Config()
        cls.contexts = {}

        class Validator:
            def validate(self, *, context_id, subject_token, correlation_id):
                from security.platform_context import ContextRejected
                from security.platform_context import ProvisioningAuthority, RUNTIME, TENANT_PROVISIONING, ValidatedContext
                authority = cls.contexts.get(context_id)
                if authority is None or authority[0] != subject_token:
                    raise ContextRejected()
                token, tenant, purpose, plan = authority
                return ValidatedContext(tenant, purpose, ProvisioningAuthority(*plan) if plan else None)

        cls.config.context_validator = Validator()
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(cls.config, key_resolver=_Key(cls.private_key.public_key()))
        )
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

    def _token(self, scope="erp:read", tenant="default", **claims):
        now = int(time.time())
        body = {"iss": ISSUER, "aud": "baobab-erp", "sub": "svc", "azp": "svc", "actor_type": "workload",
                "scope": scope, "iat": now, "exp": now + 300}
        tenant = self.tenant if tenant == "default" else tenant
        if tenant is not None:
            body["tenant_id"] = tenant
        body.update(claims)
        return jwt.encode(body, self.private_key, algorithm="RS256")

    def plan_for(self, method, path, data):
        """The plan tuple of the context a caller of this provisioning operation holds: the plan a POST names, and for a GET
        the plan the operation was accepted under (when this harness created it), else one that matches nothing."""
        if isinstance(data, dict) and isinstance(data.get("control_plane_authority"), dict):
            a = data["control_plane_authority"]
            return (a.get("tenant_provisioning_id"), a.get("plan_id"), a.get("plan_version"), a.get("plan_digest"))
        return getattr(self, "operation_plans", {}).get(path.rsplit("/", 1)[-1].split("?")[0],
                                                       ("tp_unrelated", "plan_unrelated", 1, "sha256:" + "0" * 64))

    def _call(self, method, path, token="default", headers=None, data=None):
        token = self._token() if token == "default" else token
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        context_paths = ("/inventory-availability", "/order-consequences/", "/provisioning-operations")
        if any(path.startswith(prefix) for prefix in context_paths):
            context_id = str(uuid.uuid4())
            # What a Control Plane context for this operation is authority FOR: provisioning acts before activation under
            # the approved plan; business-data reads act for an ACTIVE tenant.
            if path.startswith("/provisioning-operations"):
                plan = self.plan_for(method, path, data)
                self.contexts[context_id] = (token, self.tenant, "TENANT_PROVISIONING", plan)
            else:
                self.contexts[context_id] = (token, self.tenant, "RUNTIME", None)
            if method == "GET":
                path += ("&" if "?" in path else "?") + "context_id=" + context_id
            elif isinstance(data, dict) and "control_plane_authority" in data:
                data = dict(data, context_id=context_id)
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                         data=None if data is None else json.dumps(data).encode())
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read())

    def _mapping(self, tenant=None, legal_entity="TEST-LE-A", canonical_id=None, native_id=None, owner="trade"):
        store = PostgresCanonicalMappingStore(self.connection)
        canonical_id = canonical_id or str(uuid.uuid4())
        mapping_id = store.create_mapping(tenant or self.tenant, legal_entity, "customer", canonical_id,
                                          "C_BPartner", native_id or uuid.uuid4().int % 2_000_000_000,
                                          canonical_owner=owner)
        self.connection.commit()
        return mapping_id, canonical_id

    def assertProblem(self, status, headers, body, expected_status, code):
        self.assertEqual(status, expected_status)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertTrue(PROBLEM_REQUIRED <= set(body), body)
        self.assertEqual(body["status"], expected_status)
        self.assertEqual(body["code"], code)
        self.assertRegex(body["code"], r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
        self.assertEqual(body["correlation_id"], headers["X-Correlation-ID"])
        uuid.UUID(body["correlation_id"])

    # -- GET /mappings/{mapping_id}
    def test_get_mapping_returns_the_public_contract_document(self):
        mapping_id, canonical_id = self._mapping(native_id=424242)
        status, headers, body = self._call("GET", f"/mappings/{mapping_id}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(set(body) - {"effective_to", "replaces_mapping_id"}, MAPPING_REQUIRED)
        self.assertEqual(body["canonical_reference"],
                         {"owner": "trade", "resource_type": "customer", "resource_id": canonical_id})
        self.assertNotIn("424242", json.dumps(body))  # no iDempiere identifier leaks
        self.assertNotIn("native", json.dumps(body))

    def test_v1_base_path_is_equivalent(self):
        mapping_id, _ = self._mapping()
        self.assertEqual(self._call("GET", f"/v1/mappings/{mapping_id}")[0], 200)

    def test_mapping_of_another_tenant_is_404_not_403(self):
        mapping_id, _ = self._mapping(tenant=self.other)
        self.assertProblem(*self._call("GET", f"/mappings/{mapping_id}"), 404, "ERP_RESOURCE_NOT_FOUND")

    def test_request_cannot_widen_the_token_tenant(self):
        mapping_id, _ = self._mapping(tenant=self.other)
        self.assertProblem(*self._call("GET", f"/mappings/{mapping_id}?tenant_id={self.other}"), 404,
                           "ERP_RESOURCE_NOT_FOUND")

    def test_bad_mapping_id_is_400_with_field_error(self):
        status, headers, body = self._call("GET", "/mappings/not-a-mapping-id")
        self.assertProblem(status, headers, body, 400, "ERP_INVALID_REQUEST")
        self.assertEqual(body["errors"][0]["field"], "mapping_id")

    def test_unreconciled_mapping_is_not_visible(self):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO baobab.entity_mapping (tenant_id, canonical_type, canonical_id, native_table, native_id,"
                " status, quarantine_reason, mapping_id) VALUES (%s,'customer',%s,'C_BPartner',777001,'quarantined',"
                "'legacy','map_quarantined01')", (self.tenant, str(uuid.uuid4())))
        self.connection.commit()
        self.assertProblem(*self._call("GET", "/mappings/map_quarantined01"), 404, "ERP_RESOURCE_NOT_FOUND")

    # -- GET /mappings
    def test_find_mappings_returns_collection_and_empty_result(self):
        mapping_id, canonical_id = self._mapping()
        status, _, body = self._call("GET", f"/mappings?owner=trade&resource_type=customer&resource_id={canonical_id}")
        self.assertEqual(status, 200)
        self.assertEqual([m["mapping_id"] for m in body["items"]], [mapping_id])
        status, _, body = self._call("GET", f"/mappings?owner=trade&resource_type=customer&resource_id={uuid.uuid4()}")
        self.assertEqual((status, body), (200, {"items": []}))
        status, _, body = self._call("GET", "/mappings?owner=trade&resource_type=customer&resource_id=not-a-uuid-1")
        self.assertEqual((status, body), (200, {"items": []}))

    def test_find_mappings_is_tenant_scoped(self):
        _, canonical_id = self._mapping(tenant=self.other)
        status, _, body = self._call("GET", f"/mappings?owner=trade&resource_type=customer&resource_id={canonical_id}")
        self.assertEqual((status, body), (200, {"items": []}))

    def test_find_mappings_validates_parameters(self):
        for query in ("", "?owner=idempiere&resource_type=customer&resource_id=abc123",
                      "?owner=trade&resource_type=Customer&resource_id=abc123",
                      "?owner=trade&resource_type=customer",
                      "?owner=trade&resource_type=customer&resource_id=abc123&x=1"):
            status, headers, body = self._call("GET", "/mappings" + query)
            self.assertProblem(status, headers, body, 400, "ERP_INVALID_REQUEST")
            self.assertTrue(body["errors"])

    # -- authentication / authorisation / headers
    def test_authentication_precedes_everything(self):
        status, headers, body = self._call("GET", "/mappings/map_abcdefgh1234", token=None)
        self.assertProblem(status, headers, body, 401, "ERP_AUTHENTICATION_REQUIRED")
        status, headers, body = self._call("GET", "/mappings/map_abcdefgh1234", token="garbage")
        self.assertProblem(status, headers, body, 401, "ERP_AUTHENTICATION_REQUIRED")

    def test_scope_is_required_and_integrate_scope_is_not_enough(self):
        for scope in ("erp:integrate", "other:scope", ""):
            self.assertProblem(*self._call("GET", "/mappings/map_abcdefgh1234", token=self._token(scope=scope)),
                               403, "ERP_FORBIDDEN")

    def test_tenant_claim_is_required_for_tenant_scoped_reads(self):
        self.assertProblem(*self._call("GET", "/mappings/map_abcdefgh1234", token=self._token(tenant=None)),
                           403, "ERP_TENANT_CONTEXT_REQUIRED")

    def test_malformed_tenant_claim_is_rejected_as_unauthenticated(self):
        self.assertProblem(*self._call("GET", "/mappings/map_abcdefgh1234", token=self._token(tenant="tenant-1")),
                           401, "ERP_AUTHENTICATION_REQUIRED")

    def test_correlation_id_is_echoed_and_validated(self):
        mapping_id, _ = self._mapping()
        cid = str(uuid.uuid4())
        _, headers, _ = self._call("GET", f"/mappings/{mapping_id}", headers={"X-Correlation-ID": cid})
        self.assertEqual(headers["X-Correlation-ID"], cid)
        _, headers, _ = self._call("GET", f"/mappings/{mapping_id}")
        uuid.UUID(headers["X-Correlation-ID"])
        self.assertProblem(*self._call("GET", f"/mappings/{mapping_id}", headers={"X-Correlation-ID": "nope"}),
                           400, "ERP_INVALID_REQUEST")

    def test_traceparent_is_validated_and_surfaces_as_trace_id(self):
        trace = "0af7651916cd43dd8448eb211c80319c"
        status, headers, body = self._call("GET", "/mappings/bad", headers={"traceparent": f"00-{trace}-b7ad6b7169203331-01"})
        self.assertEqual(body["trace_id"], trace)
        self.assertProblem(*self._call("GET", "/mappings/bad", headers={"traceparent": "00-zz-b7ad6b7169203331-01"}),
                           400, "ERP_INVALID_REQUEST")

    # -- every operation of the contract is served; the 501 route stays only for a later declared-but-unbuilt operation
    def test_no_contract_operation_answers_501(self):
        from application import boundary
        for method, path in [("GET", "/mappings"), ("GET", "/mappings/map_abcdef12"), ("GET", "/order-consequences/x"),
                             ("GET", "/inventory-availability"), ("POST", "/provisioning-operations"),
                             ("GET", "/provisioning-operations/x")]:
            route = boundary.match(method, path)
            self.assertIsNotNone(route, (method, path))
            self.assertIsNot(route.handler, boundary.not_implemented, (method, path))

    def test_inventory_availability_requires_the_read_scope_then_validates_the_query(self):
        self.assertProblem(*self._call("GET", "/inventory-availability?sku_id=a", token=self._token(scope="erp:integrate")),
                           403, "ERP_FORBIDDEN")
        self.assertProblem(*self._call("GET", "/inventory-availability?sku_id=a"), 400, "ERP_INVALID_REQUEST")

    @staticmethod
    def _provisioning_request(tenant):
        return {"tenant_id": tenant, "legal_entity_ids": ["ZURIBEANS-ZA"], "requested_countries": ["ZA"],
                "functional_currencies": ["ZAR"],
                "finance_baselines": [{"baseline_id": "fb_" + "a" * 32, "legal_entity_id": "ZURIBEANS-ZA", "version": 1,
                                       "digest": "sha256:" + "c1" * 32, "effective_from": "2026-10-01",
                                       "authority": {"engine_id": "baobab-erp", "system_of_record": "FINANCE_BASELINE"}}],
                "control_plane_authority": {"tenant_provisioning_id": "tp_0199a1b2c3d47e8f9a0b1c2d3e4f5a6b",
                                            "plan_id": "plan_0199a1b2c3d47e8f", "plan_version": 1,
                                            "plan_digest": "sha256:" + "b2" * 32}}

    # -- provisioning operations (handler-level behaviour is in test_provisioning_operations.py)
    def test_provisioning_operations_are_served_not_501(self):
        key = {"Idempotency-Key": "idem-" + "0123456789abcdef"}
        self.assertProblem(*self._call("POST", "/provisioning-operations", token=self._token(scope="erp:provision"),
                                       headers=key, data={"tenant_id": self.tenant}), 400, "ERP_INVALID_REQUEST")
        self.assertProblem(*self._call("POST", "/provisioning-operations", token=self._token(scope="erp:provision"),
                                       headers=key, data=self._provisioning_request(self.other)), 403, "ERP_CONTEXT_REJECTED")
        self.assertProblem(*self._call("POST", "/provisioning-operations", token=self._token(scope="erp:read"),
                                       headers=key, data={}), 403, "ERP_FORBIDDEN")
        # Following an operation is part of provisioning (Shared erp/v1 1.1.1): erp:provision, never erp:read.
        provisioner = self._token(scope="erp:provision")
        self.assertProblem(*self._call("GET", f"/provisioning-operations/{uuid.uuid4()}", token=provisioner),
                           404, "ERP_RESOURCE_NOT_FOUND")
        self.assertProblem(*self._call("GET", "/provisioning-operations/op_nope", token=provisioner), 400, "ERP_INVALID_REQUEST")
        self.assertProblem(*self._call("GET", f"/provisioning-operations/{uuid.uuid4()}", token=self._token(scope="erp:read")),
                           403, "ERP_FORBIDDEN")

    def test_the_finance_baseline_reads_are_provisioning_not_business_data_reads(self):
        # Shared erp/v1 1.3.0: resolving a Finance baseline reference is part of provisioning, so erp:provision, never erp:read.
        reader = self._token(scope="erp:read")
        digest = "sha256:" + "c1" * 32
        for path in ("/legal-entities/ZURIBEANS-ZA/effective-finance-baseline",
                     f"/finance-baselines/fb_{'a' * 32}?version=1&digest={digest}"):
            with self.subTest(path):
                self.assertProblem(*self._call("GET", path, token=reader), 403, "ERP_FORBIDDEN")

    def test_provisioning_is_unavailable_until_control_plane_is_configured(self):
        valid = self._provisioning_request(self.tenant)
        status, headers, body = self._call("POST", "/provisioning-operations", token=self._token(scope="erp:provision"),
                                           headers={"Idempotency-Key": "idem-" + "0123456789abcdef"}, data=valid)
        self.assertProblem(status, headers, body, 503, "ERP_SERVICE_UNAVAILABLE")
        self.assertEqual(headers["Retry-After"], "30")

    def test_legacy_routes_are_untouched(self):
        status, _, body = self._call("GET", "/health/live", token=None)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()

