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
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.config, key_resolver=_Key(cls.key.public_key())))
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
            cleanup = getattr(self, "inventory_cleanup", None)
            if cleanup:
                cursor.execute("DELETE FROM baobab.erp_master_data_mapping WHERE engine_instance_id = %s", (cleanup[1],))
                cursor.execute("DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s", (self.tenant,))
            cursor.execute("DELETE FROM baobab.order_consequence_document WHERE tenant_id = ANY(%s)",
                           ([self.tenant, self.other],))
            cursor.execute("DELETE FROM baobab.order_consequence WHERE tenant_id = ANY(%s)", ([self.tenant, self.other],))
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

    def plan_for(self, method, path, data):
        """The plan tuple of the context a caller of this provisioning operation holds: the plan a POST names, and for a GET
        the plan the operation was accepted under (when this harness created it), else one that matches nothing."""
        if isinstance(data, dict) and isinstance(data.get("control_plane_authority"), dict):
            a = data["control_plane_authority"]
            return (a.get("tenant_provisioning_id"), a.get("plan_id"), a.get("plan_version"), a.get("plan_digest"))
        return getattr(self, "operation_plans", {}).get(path.rsplit("/", 1)[-1].split("?")[0],
                                                       ("tp_unrelated", "plan_unrelated", 1, "sha256:" + "0" * 64))

    def _call(self, method, path, token="default", data=None, headers=None):
        headers = dict(headers or {})
        token = self._token() if token == "default" else token
        if token:
            headers["Authorization"] = f"Bearer {token}"
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
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers,
                                         data=None if data is None else json.dumps(data).encode())
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
        self.assertIn(status, declared, f"{method} {template} returned {status}, which the pinned OpenAPI does not declare")
        self.assertIn(content_type, shared.declared_media(template, method, status), (status, content_type))
        self.assertEqual(shared.errors_for(template, method, status, content_type, body), [], body)
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

    # -- inventory availability: the engine's physical stock, read live
    def test_every_status_inventory_availability_can_return_conforms(self):
        template = "/inventory-availability"
        ok = "sku_id=sku-1&warehouse_id=erp_abcdef12"
        cases = [
            (f"/inventory-availability?{ok}", dict(), 404),                                   # unmapped warehouse
            ("/inventory-availability", dict(), 400),
            ("/inventory-availability?sku_id=sku-1&warehouse_id=nope", dict(), 400),
            (f"/inventory-availability?{ok}", dict(token=None), 401),
            (f"/inventory-availability?{ok}", dict(token=self._token(scope="erp:integrate")), 403),
            (f"/inventory-availability?{ok}", dict(token=self._token(tenant=None)), 404),
        ]
        for path, kwargs, expected in cases:
            with self.subTest(path=path, expected=expected):
                status, *_ = self.assert_contract("GET", template, self._call("GET", path, **kwargs))
                self.assertEqual(status, expected)

    def test_an_engine_that_cannot_be_reached_is_a_declared_503_with_no_figure(self):
        sku = f"sku-{uuid.uuid4().hex[:12]}"
        warehouse = self._inventory_mappings(sku)
        status, headers, body = self.assert_contract(
            "GET", "/inventory-availability",
            self._call("GET", f"/inventory-availability?sku_id={sku}&warehouse_id={warehouse}"))
        self.assertEqual((status, headers.get("Retry-After")), (503, "30"))  # no iDempiere credentials in this deployment
        self.assertNotIn("on_hand", body)

    def test_the_inventory_availability_document_matches_the_declared_200_schema(self):
        from datetime import datetime, timezone
        from application.inventory_availability import get_inventory_availability

        class Engine:
            def get_record(self, table, record_id):
                return {"C_UOM_ID": 100} if table == "M_Product" else {"X12DE355": "KG"}

            def query(self, table, conditions, select):
                return {"M_Locator": [{"M_Locator_ID": 5}],
                        "M_StorageOnHand": [{"M_Locator_ID": 5, "QtyOnHand": "12.250", "Updated": "2026-10-02T09:00:00Z"}],
                        "M_StorageReservation": [{"Qty": 2, "Updated": "2026-10-02T09:30:00Z"}]}[table]

        sku = f"sku-{uuid.uuid4().hex[:12]}"
        warehouse = self._inventory_mappings(sku)
        status, body, _ = get_inventory_availability(
            tenant_id=self.tenant, query_string=f"sku_id={sku}&warehouse_id={warehouse}", connection=self.connection,
            correlation_id=str(uuid.uuid4()), trace_id=None, idempiere_for=lambda ad_client_id: Engine(),
            now=lambda: datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(status, 200, body)
        self.assertEqual(shared.errors_for("/inventory-availability", "GET", 200, "application/json", body), [])
        self.assertEqual((body["on_hand"]["value"], body["erp_available"]["value"], body["on_hand"]["unit"]),
                         ("12.25", "10.25", "KG"))

    def _inventory_mappings(self, sku):
        """Committed so the HTTP server sees them; removed in _cleanup."""
        entity, instance = f"ZB-{uuid.uuid4().hex[:10].upper()}", f"ei_{uuid.uuid4().hex[:10]}"
        self.inventory_cleanup = (entity, instance)
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, "
                           "legal_entity_id, engine_instance_id) VALUES (%s,%s,1001,1,%s,%s)",
                           (self.tenant, entity, entity, instance))
            cursor.execute("INSERT INTO baobab.erp_master_data_mapping (engine_instance_id, legal_entity_id, resource_kind, "
                           "canonical_id, native_id, desired_digest, source_version) VALUES (%s,%s,'product',%s,77,'d','1')",
                           (instance, entity, sku))
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.erp_warehouse (tenant_id, legal_entity_id, code, engine_instance_id, native_id) "
                           "VALUES (%s,%s,'MAIN',%s,88) RETURNING erp_resource_id", (self.tenant, entity, instance))
            warehouse = cursor.fetchone()[0]
        self.connection.commit()
        return warehouse

    def test_pinned_openapi_declares_the_statuses_erp_returns(self):
        """Shared 1.0.5: 400 on the mapping reads and the inventory read, 503 on the inventory read, and no transitional
        501 on any operation, because ERP serves every one."""
        for template in ("/mappings/{mapping_id}", "/mappings", "/inventory-availability"):
            self.assertIn(400, shared.declared_statuses(template, "GET"), template)
        self.assertIn(503, shared.declared_statuses("/inventory-availability", "GET"))
        for method, template in [("POST", "/provisioning-operations"), ("GET", "/provisioning-operations/{operation_id}"),
                                 ("GET", "/order-consequences/{commerce_order_id}"), ("GET", "/inventory-availability")]:
            self.assertNotIn(501, shared.declared_statuses(template, method), (method, template))

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
