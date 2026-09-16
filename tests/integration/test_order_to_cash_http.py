"""End-to-end proof of the sell-side order-to-cash HTTP surface (ADR-ERP-016):
real HTTP requests against application.server's Handler, a real Postgres
database (context/mapping/outbox all really written to and read back), and a
fake local server reproducing iDempiere's own REST API shape exactly (per
integration.idempiere_client's own verified spec) standing in for a live
iDempiere instance, which no environment this code has run in yet has (see
that module's own docstring). This is the strongest verification available
without a real iDempiere instance: every piece of the pipeline this repository
owns is exercised for real; only iDempiere's own actual behaviour is faked.
"""

import json
import os
import random
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from threading import Thread

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

from _postgres import require_database_url

SECRET = "integration-test-secret"
OIDC_ISSUER = "https://iam.example.invalid/realms/baobab"


class _FixedKeyResolver:
    def __init__(self, key):
        self._key = key

    def resolve(self, token: str):
        return self._key


class _FakeIdempiereHandler(BaseHTTPRequestHandler):
    """Reproduces exactly the request/response shapes RestIdempiereClient sends
    and expects (integration.idempiere_client's own docstring: verified against
    the com.trekglobal.idempiere.rest.api / bxservice/idempiere-rest OpenAPI
    spec). Assigns sequential native ids starting at 5000 so assertions can
    tell records apart without coordinating on exact values."""

    _next_native_id = 5000

    def log_message(self, format, *args):  # noqa: A002
        pass

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_POST(self):  # noqa: N802
        body = self._read_json()
        if self.path == "/auth/tokens":
            self._send_json(200, {"token": "fake-access-token", "refresh_token": "fake-refresh-token", "userId": 100})
            return
        if self.path == "/auth/refresh":
            self._send_json(200, {"token": "fake-access-token-2", "refresh_token": "fake-refresh-token", "userId": 100})
            return
        if self.path.startswith("/models/"):
            table = self.path.removeprefix("/models/")
            type(self)._next_native_id += 1
            _FakeIdempiereHandler._created.setdefault(table, []).append(body)
            self._send_json(201, {"id": type(self)._next_native_id})
            return
        if self.path.startswith("/processes/"):
            process_id = self.path.removeprefix("/processes/")
            _FakeIdempiereHandler._processes_executed.append((process_id, body))
            self._send_json(200, {"IsError": False})
            return
        self._send_json(404, {"title": "Not Found", "status": 404, "detail": self.path})

    _created: dict[str, list[dict]] = {}
    _processes_executed: list[tuple[str, dict]] = []


class OrderToCashHttpIntegrationTests(unittest.TestCase):
    AD_CLIENT_ID = 424242
    PROCESS_IDS = {
        "IDEMPIERE_PROCESS_COMPLETE_SALES_ORDER": "9001",
        "IDEMPIERE_PROCESS_COMPLETE_SHIPMENT": "9002",
        "IDEMPIERE_PROCESS_POST_CUSTOMER_INVOICE": "9003",
        "IDEMPIERE_PROCESS_COMPLETE_PAYMENT": "9004",
        "IDEMPIERE_PROCESS_ALLOCATE_PAYMENT": "9005",
    }

    @classmethod
    def setUpClass(cls):
        database_url = require_database_url()  # skips the whole class if unset
        os.environ["DATABASE_URL"] = database_url
        os.environ["BAOBAB_EVENT_SIGNING_SECRET"] = SECRET
        os.environ["BAOBAB_IAM_OIDC_ISSUER"] = OIDC_ISSUER
        os.environ.update(cls.PROCESS_IDS)

        cls.fake_idempiere = HTTPServer(("127.0.0.1", 0), _FakeIdempiereHandler)
        cls.fake_idempiere_port = cls.fake_idempiere.server_address[1]
        cls.fake_idempiere_thread = Thread(target=cls.fake_idempiere.serve_forever, daemon=True)
        cls.fake_idempiere_thread.start()

        os.environ["IDEMPIERE_CLIENT_CREDENTIALS_JSON"] = json.dumps({
            str(cls.AD_CLIENT_ID): {
                "base_url": f"http://127.0.0.1:{cls.fake_idempiere_port}",
                "username": "fake-user",
                "password": "fake-password",
                "client_id": cls.AD_CLIENT_ID,
                "role_id": 1,
                "organization_id": 1,
            }
        })

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.workload_token = cls._mint_workload_token(private_key)

        from application.server import Config, make_handler

        config = Config()
        cls.assertIsNotNone_(config.order_to_cash_process_ids, "process ids must have loaded from env")
        handler = make_handler(config, key_resolver=_FixedKeyResolver(private_key.public_key()))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @staticmethod
    def assertIsNotNone_(value, message):
        if value is None:
            raise AssertionError(message)

    @staticmethod
    def _mint_workload_token(private_key, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": OIDC_ISSUER, "aud": "baobab-erp", "sub": "service-account-baobab-trade-workload",
            "azp": "baobab-trade-workload", "actor_type": "workload", "scope": "erp:integrate",
            "iat": now, "exp": now + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.fake_idempiere.shutdown()
        cls.fake_idempiere.server_close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _post(self, path: str, body: dict, *, as_workload: bool = True):
        headers = {"Content-Type": "application/json"}
        if as_workload:
            headers["Authorization"] = f"Bearer {self.workload_token}"
        request = urllib.request.Request(
            self._url(path), data=json.dumps(body).encode(), method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _register_tenant(self) -> tuple[str, str]:
        """Inserts a real baobab.tenant_mapping row so context resolution has
        something real to find, matching test_http_server.py's own pattern."""
        tenant_id = f"test-o2c-tenant-{uuid.uuid4()}"
        entity_id = f"test-o2c-entity-{uuid.uuid4()}"
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id) "
                    "VALUES (%s, %s, %s, %s)",
                    (tenant_id, entity_id, self.AD_CLIENT_ID, 1),
                )
            connection.commit()
        self.addCleanup(self._cleanup_tenant, tenant_id)
        return tenant_id, entity_id

    def _register_tenant_with_unconfigured_client(self) -> tuple[str, str]:
        """A tenant mapped to an AD_Client this test's IDEMPIERE_CLIENT_CREDENTIALS_JSON
        does NOT cover -- proves the UnconfiguredIdempiereClient fail-closed path end
        to end, not just in the unit tests."""
        tenant_id = f"test-o2c-unconfigured-{uuid.uuid4()}"
        entity_id = f"test-o2c-unconfigured-entity-{uuid.uuid4()}"
        unconfigured_ad_client_id = random.randint(1_000_000, 9_999_999)
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id) "
                    "VALUES (%s, %s, %s, %s)",
                    (tenant_id, entity_id, unconfigured_ad_client_id, 1),
                )
            connection.commit()
        self.addCleanup(self._cleanup_tenant, tenant_id)
        return tenant_id, entity_id

    def _cleanup_tenant(self, tenant_id: str) -> None:
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s", (tenant_id,))
                cursor.execute("DELETE FROM baobab.entity_mapping WHERE tenant_id = %s", (tenant_id,))
                cursor.execute("DELETE FROM baobab.event_outbox WHERE tenant_id = %s", (tenant_id,))
            connection.commit()

    def _outbox_rows(self, tenant_id: str) -> list[tuple[str, str]]:
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT event_type, correlation_id FROM baobab.event_outbox "
                    "WHERE tenant_id = %s ORDER BY occurred_at",
                    (tenant_id,),
                )
                return cursor.fetchall()

    def test_full_sell_side_pipeline_end_to_end(self):
        tenant_id, entity_id = self._register_tenant()
        commerce_order_id = str(uuid.uuid4())

        status, body = self._post("/sales-orders", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": commerce_order_id,
            "business_partner_native_id": 42, "document_currency": "UGX",
            "lines": [{"product_canonical_id": "prod-1", "quantity": "10", "unit_price": "4.50"}],
        })
        self.assertEqual(status, 201, body)
        self.assertEqual(body["table"], "C_Order")
        order_native_id = body["native_id"]

        status, body = self._post("/sales-orders/complete", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": commerce_order_id, "correlation_id": "corr-1",
        })
        self.assertEqual(status, 200, body)

        shipment_id = str(uuid.uuid4())
        status, body = self._post("/shipments", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "shipment_canonical_id": shipment_id, "commerce_order_canonical_id": commerce_order_id,
        })
        self.assertEqual(status, 201, body)

        status, body = self._post("/shipments/complete", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "shipment_canonical_id": shipment_id, "correlation_id": "corr-1",
        })
        self.assertEqual(status, 200, body)

        status, body = self._post("/customer-invoices", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": commerce_order_id,
        })
        self.assertEqual(status, 201, body)
        invoice_canonical_id = body["canonical_id"]

        status, body = self._post("/customer-invoices/post", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "invoice_canonical_id": invoice_canonical_id, "correlation_id": "corr-1",
        })
        self.assertEqual(status, 200, body)

        payment_id = str(uuid.uuid4())
        status, body = self._post("/payments", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "payment_canonical_id": payment_id, "business_partner_native_id": 42,
            "amount": "45.00", "currency": "UGX",
        })
        self.assertEqual(status, 201, body)

        status, body = self._post("/payments/complete", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "payment_canonical_id": payment_id, "correlation_id": "corr-1",
        })
        self.assertEqual(status, 200, body)

        status, body = self._post("/payments/allocate", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "payment_canonical_id": payment_id, "invoice_canonical_id": invoice_canonical_id,
            "amount": "45.00", "correlation_id": "corr-1",
        })
        self.assertEqual(status, 200, body)

        # Real Postgres proof: exactly the five distinct canonical facts, in order.
        event_types = [row[0] for row in self._outbox_rows(tenant_id)]
        self.assertEqual(event_types, [
            "erp.sales-order.accepted.v1",
            "erp.goods-shipment.completed.v1",
            "erp.customer-invoice.posted.v1",
            "erp.payment.completed.v1",
            "erp.payment.allocated.v1",
        ])

        # Real fake-iDempiere proof: every *_complete/_post call invoked its
        # configured native process (never a direct field patch).
        executed_process_ids = {process_id for process_id, _ in _FakeIdempiereHandler._processes_executed}
        self.assertTrue({"9001", "9002", "9003", "9004", "9005"} <= executed_process_ids)

    def test_create_sales_order_missing_fields_is_400(self):
        status, _ = self._post("/sales-orders", {"tenant_id": "x", "entity_id": "y"})
        self.assertEqual(status, 400)

    def test_create_sales_order_unresolved_tenant_is_404(self):
        status, _ = self._post("/sales-orders", {
            "tenant_id": "no-such-tenant", "entity_id": "no-such-entity",
            "commerce_order_canonical_id": str(uuid.uuid4()), "business_partner_native_id": 1,
            "document_currency": "UGX", "lines": [{"product_canonical_id": "p", "quantity": "1", "unit_price": "1"}],
        })
        self.assertEqual(status, 404)

    def test_order_to_cash_endpoints_require_a_workload_token(self):
        status, _ = self._post("/sales-orders", {}, as_workload=False)
        self.assertEqual(status, 401)

    def test_complete_sales_order_against_unmapped_order_is_404(self):
        tenant_id, entity_id = self._register_tenant()
        status, _ = self._post("/sales-orders/complete", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": str(uuid.uuid4()), "correlation_id": "corr-x",
        })
        self.assertEqual(status, 404)

    def test_complete_sales_order_with_malformed_canonical_id_is_400_not_a_crash(self):
        # Regression test: entity_mapping.canonical_id is a native Postgres UUID
        # column: a malformed value used to reach psycopg unvalidated and crash the
        # connection (a raw, uncaught psycopg.errors.InvalidTextRepresentation)
        # instead of returning a clean 400.
        tenant_id, entity_id = self._register_tenant()
        status, body = self._post("/sales-orders/complete", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": "not-a-uuid", "correlation_id": "corr-x",
        })
        self.assertEqual(status, 400, body)

    def test_create_sales_order_with_malformed_canonical_id_is_400_not_a_crash(self):
        tenant_id, entity_id = self._register_tenant()
        status, body = self._post("/sales-orders", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": "not-a-uuid", "business_partner_native_id": 1,
            "document_currency": "UGX", "lines": [{"product_canonical_id": "p", "quantity": "1", "unit_price": "1"}],
        })
        self.assertEqual(status, 400, body)

    def test_outbox_record_end_to_end(self):
        tenant_id = f"test-outbox-{uuid.uuid4()}"
        event_type = "erp.sales-order.synced.v1"
        status, body = self._post("/outbox/record", {
            "event_type": event_type, "tenant_id": tenant_id, "entity_id": "legal-1",
            "correlation_id": "corr-outbox-1", "payload": {"table": "C_Order", "native_record_id": 1001},
        })
        self.assertEqual(status, 202, body)
        self.addCleanup(self._cleanup_tenant, tenant_id)

        rows = self._outbox_rows(tenant_id)
        self.assertEqual(rows, [(event_type, "corr-outbox-1")])

    def test_outbox_record_missing_fields_is_400(self):
        status, _ = self._post("/outbox/record", {"event_type": "x"})
        self.assertEqual(status, 400)

    def test_outbox_record_without_a_token_is_401(self):
        status, _ = self._post("/outbox/record", {}, as_workload=False)
        self.assertEqual(status, 401)

    def test_create_sales_order_against_unconfigured_ad_client_is_502_not_a_crash(self):
        tenant_id, entity_id = self._register_tenant_with_unconfigured_client()
        status, body = self._post("/sales-orders", {
            "tenant_id": tenant_id, "entity_id": entity_id,
            "commerce_order_canonical_id": str(uuid.uuid4()), "business_partner_native_id": 1,
            "document_currency": "UGX", "lines": [{"product_canonical_id": "p", "quantity": "1", "unit_price": "1"}],
        })
        self.assertEqual(status, 502, body)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
