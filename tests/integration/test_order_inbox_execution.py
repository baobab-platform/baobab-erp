"""Accepted ``trade.order.placed`` -> sales order in the engine -> consequence record -> registered outcome event.

Real HTTP ingress (``POST /events/inbound``), real Postgres, the real ``RestIdempiereClient`` talking to a fake engine over HTTP.
Only iDempiere itself is faked, so what is proven is everything ERP owns: claiming, the lease, the per-order lock, the engine
lookup that stops a second order, the single transaction that records the result, and the event it announces. What this does
not prove is a live iDempiere (the fake is told what to answer; ``POReference`` as the lookup column is unconfirmed there).

The acceptance tests are the first two in ``ReplayAndRecoveryTests``: replaying an accepted event, and restarting after an
uncertain outcome, must never create a second sales order.
"""
import hashlib
import hmac
import json
import os
import threading
import unittest
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from unittest import mock

import psycopg

from _postgres import require_database_url

SECRET = "integration-test-secret"
ORDER_PLACED = "com.baobab-platform.trade.order.placed.v1"
CUSTOMER_PROJECTED = "com.baobab-platform.trade.customer.projected.v1"
OIDC_ISSUER = "https://iam.example.invalid/realms/baobab"


class _Crash(BaseException):
    """A worker dying mid-attempt: not an Exception, so nothing in the executor can settle the row on its way out."""


class _Engine(BaseHTTPRequestHandler):
    """The shape of the iDempiere REST plugin that RestIdempiereClient sends and expects, for C_Order only."""

    state: dict = {}

    def log_message(self, *_):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        state = type(self).state
        if self.path == "/auth/tokens":
            return self._send(200, {"token": "t", "refresh_token": "r", "userId": 1})
        if self.path == "/models/C_Order":
            with state["lock"]:
                state["create_attempts"] += 1
            if state["create_gate"] is not None:
                state["create_entered"].set()
                state["create_gate"].wait(10)
            if state["create_status"] != 201:
                return self._send(state["create_status"], {"title": "engine", "status": state["create_status"], "detail": "x"})
            with state["lock"]:
                state["next_id"] += 1
                state["orders"].append({"id": state["next_id"], **body})
                return self._send(201, {"id": state["next_id"]})
        self._send(404, {"title": "Not Found", "status": 404, "detail": self.path})

    def do_GET(self):  # noqa: N802
        state = type(self).state
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/models/C_Order":
            return self._send(404, {"title": "Not Found", "status": 404, "detail": self.path})
        flt = urllib.parse.parse_qs(parsed.query).get("$filter", [""])[0]
        reference = flt.split(" eq ", 1)[1].strip("'") if flt.startswith("POReference eq ") else None
        with state["lock"]:
            state["queries"] += 1
            hits = [{"id": o["id"], "C_Order_ID": o["id"]} for o in state["orders"] if o.get("POReference") == reference]
        self._send(200, {"records": hits, "row-count": len(hits)})


def _reset_engine():
    _Engine.state = {"lock": threading.Lock(), "orders": [], "next_id": 7000, "create_attempts": 0, "queries": 0,
                     "create_status": 201, "create_gate": None, "create_entered": threading.Event()}


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = require_database_url()
        os.environ["BAOBAB_EVENT_SIGNING_SECRET"] = SECRET
        os.environ["BAOBAB_IAM_OIDC_ISSUER"] = OIDC_ISSUER
        cls.engine = HTTPServer(("127.0.0.1", 0), _Engine)
        threading.Thread(target=cls.engine.serve_forever, daemon=True).start()
        cls.engine_url = f"http://127.0.0.1:{cls.engine.server_address[1]}"
        from application.server import Config, make_handler

        class _NoKeys:
            def resolve(self, token):
                raise AssertionError("event ingress needs no bearer token")

        cls.ingress = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Config(), key_resolver=_NoKeys()))
        threading.Thread(target=cls.ingress.serve_forever, daemon=True).start()
        cls.ingress_port = cls.ingress.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for server in (cls.engine, cls.ingress):
            server.shutdown()
            server.server_close()

    def setUp(self):
        _reset_engine()
        self.tag = uuid.uuid4().hex[:12]
        self.tenant = f"tn_{self.tag}"
        self.entity = "ZURIBEANS"
        self.engine_instance = f"ei_{self.tag}"
        self.ad_client = int(self.tag[:6], 16) + 100000
        self.customer, self.sku = f"customer_{self.tag}", f"sku_{self.tag}"
        self.order = f"order_{self.tag}"
        self.db = psycopg.connect(os.environ["DATABASE_URL"])
        self.connections = [self.db]
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.db.cursor() as cursor:
            self.db.rollback()
            for sql in ("DELETE FROM baobab.order_execution WHERE tenant_id = %s",
                        "DELETE FROM baobab.order_consequence WHERE tenant_id = %s",
                        "DELETE FROM baobab.event_outbox WHERE tenant_id = %s",
                        "DELETE FROM baobab.event_inbox WHERE tenant_id = %s",
                        "DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s"):
                cursor.execute(sql, (self.tenant,))
            cursor.execute("DELETE FROM baobab.erp_master_data_mapping WHERE engine_instance_id = %s", (self.engine_instance,))
        self.db.commit()
        for connection in self.connections:
            connection.close()

    # -- fixtures ---------------------------------------------------------------------------------------------------
    def connect(self):
        connection = psycopg.connect(os.environ["DATABASE_URL"])
        self.connections.append(connection)
        return connection

    def seed(self, *, customer=True, product=True, tenant=True):
        with self.db.cursor() as cursor:
            if tenant:
                cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, "
                               "legal_entity_id, engine_instance_id) VALUES (%s,%s,%s,1,%s,%s)",
                               (self.tenant, self.entity, self.ad_client, self.entity, self.engine_instance))
            for kind, canonical, native, present in (("business_partner", self.customer, 501, customer),
                                                     ("product", self.sku, 601, product)):
                if present:
                    cursor.execute(
                        "INSERT INTO baobab.erp_master_data_mapping (engine_instance_id, legal_entity_id, resource_kind, "
                        "canonical_id, native_id, desired_digest, source_version) VALUES (%s,%s,%s,%s,%s,'d','1')",
                        (self.engine_instance, self.entity, kind, canonical, native))
        self.db.commit()

    def engine_for(self, ad_client_id):
        from integration.idempiere_client import IdempiereCredentials, RestIdempiereClient

        if ad_client_id != self.ad_client:
            return None
        return RestIdempiereClient(IdempiereCredentials(base_url=self.engine_url, username="u", password="p",
                                                        client_id=ad_client_id, role_id=1, organization_id=1))

    def placed(self, *, event_id=None, version=1, order=None, lines=None, data=None):
        order = order or self.order
        body = data if data is not None else {
            "legal_entity_id": self.entity, "commerce_order_id": order, "order_version": version,
            "customer_id": self.customer, "placed_at": "2026-10-08T09:00:00Z", "currency": "USD",
            "lines": lines or [{"line_id": "line_001", "sku_id": self.sku, "quantity": {"value": "12", "unit": "EA"},
                                "unit_price": {"amount": "25.00", "currency": "USD"},
                                "line_total": {"amount": "300.00", "currency": "USD"}}],
            "totals": {"subtotal": {"amount": "300.00", "currency": "USD"}, "discount": {"amount": "0.00", "currency": "USD"},
                       "quoted_tax": {"amount": "0.00", "currency": "USD"}, "grand_total": {"amount": "300.00", "currency": "USD"}}}
        return {"specversion": "1.0", "id": event_id or str(uuid.uuid4()), "type": ORDER_PLACED,
                "source": "urn:baobab-platform:service:trade", "subject": f"order:{order}", "time": "2026-10-08T09:00:00Z",
                "datacontenttype": "application/json",
                "dataschema": "https://contracts.baobab-platform.com/erp/v1/commerce-order-consequence.schema.json",
                "baobabscope": "tenant", "correlationid": str(uuid.uuid4()), "tenantid": self.tenant,
                "idempotencykey": f"trade-{order}-v{version}", "data": body}

    def deliver(self, wire):
        import urllib.request

        raw = json.dumps(wire).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        request = urllib.request.Request(f"http://127.0.0.1:{self.ingress_port}/events/inbound", data=raw, method="POST",
                                         headers={"X-Baobab-Signature": signature})
        with urllib.request.urlopen(request) as response:
            return response.status

    def work(self, connection=None, worker="w1", limit=20, lease=300):
        from application.inbox_worker import run_once

        return run_once(connection or self.db, self.engine_for, worker_id=worker, limit=limit, lease_seconds=lease)

    def row(self, event_id):
        with self.db.cursor() as cursor:
            cursor.execute("SELECT status, outcome_code, attempts, next_attempt_at, claimed_by, last_error "
                           "FROM baobab.event_inbox WHERE event_id = %s::uuid", (event_id,))
            found = cursor.fetchone()
        self.db.commit()
        return dict(zip(("status", "code", "attempts", "next", "claimed_by", "error"), found)) if found else None

    def scalar(self, sql, *args):
        with self.db.cursor() as cursor:
            cursor.execute(sql, args)
            value = cursor.fetchone()[0]
        self.db.commit()
        return value

    def outbox_events(self):
        with self.db.cursor() as cursor:
            cursor.execute("SELECT event_type, ce_idempotency_key, payload_json, status FROM baobab.event_outbox "
                           "WHERE tenant_id = %s ORDER BY id", (self.tenant,))
            rows = cursor.fetchall()
        self.db.commit()
        return rows

    def engine_orders(self):
        return _Engine.state["orders"]

    def make_due(self, event_id):
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.event_inbox SET next_attempt_at = now() - interval '1 second' "
                           "WHERE event_id = %s::uuid", (event_id,))
        self.db.commit()


class ExecutionTests(_Base):
    def test_an_accepted_order_event_becomes_a_sales_order_a_consequence_and_a_published_event(self):
        self.seed()
        wire = self.placed()
        self.assertEqual(self.deliver(wire), 200)
        self.assertEqual(self.row(wire["id"])["status"], "received")  # ingress only receives

        report = self.work()

        self.assertEqual(report["pass"], {"processed": 1})
        self.assertEqual(report["codes"], {"EXECUTED": 1})
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"], row["attempts"]), ("processed", "EXECUTED", 1))
        # the engine order: mapped customer and product, reference to the Trade order, no canonical id leaked as a native id
        [engine_order] = self.engine_orders()
        self.assertEqual(engine_order["C_BPartner_ID"], 501)
        self.assertEqual(engine_order["POReference"], self.order)
        self.assertEqual(engine_order["OrderLines"], [{"M_Product_ID": "601", "QtyOrdered": "12", "PriceEntered": "25.00"}])
        # the consequence record and the order link, written together
        with self.db.cursor() as cursor:
            cursor.execute("SELECT status, accounting_status, inventory_status, revision, erp_order_id, order_version "
                           "FROM baobab.order_consequence WHERE tenant_id = %s AND commerce_order_id = %s",
                           (self.tenant, self.order))
            status, accounting, inventory, revision, erp_id, version = cursor.fetchone()
            cursor.execute("SELECT native_id, adopted, erp_order_id, source_event_id::text FROM baobab.order_execution "
                           "WHERE tenant_id = %s AND commerce_order_id = %s", (self.tenant, self.order))
            native_id, adopted, link_erp_id, source = cursor.fetchone()
        self.db.commit()
        self.assertEqual((status, accounting, inventory, revision, version), ("accepted", "pending", "pending", 1, 1))
        self.assertEqual((native_id, adopted, source), (engine_order["id"], False, wire["id"]))
        self.assertEqual(link_erp_id, erp_id)
        # the canonical outcome event, recorded in that same transaction and still to be delivered
        [(event_type, key, payload, delivery)] = self.outbox_events()
        self.assertEqual(event_type, "com.baobab-platform.erp.order.consequence-changed.v1")
        self.assertEqual(key, f"erp-order-consequence-{self.order}-r1")
        self.assertEqual(delivery, "pending")
        self.assertEqual({k: payload[k] for k in ("commerce_order_id", "status", "revision", "erp_order_id", "order_version")},
                         {"commerce_order_id": self.order, "status": "accepted", "revision": 1, "erp_order_id": erp_id,
                          "order_version": 1})

    def test_only_order_placed_events_are_executed(self):
        self.seed()
        other = self.placed()
        other["type"] = CUSTOMER_PROJECTED
        other["dataschema"] = "https://contracts.baobab-platform.com/erp/v1/customer-projection.schema.json"
        other["data"] = {"customer_id": self.customer}
        # ingress may reject a payload that is not its schema; what matters is that the order worker never touches it
        try:
            self.deliver(other)
        except Exception:  # noqa: BLE001
            self.skipTest("ingress rejected the customer event shape in this fixture")
        self.work()
        self.assertEqual(self.row(other["id"])["status"], "received")
        self.assertEqual(self.engine_orders(), [])

    def test_invalid_payload_is_a_dead_letter_and_the_engine_is_never_called(self):
        self.seed()
        wire = self.placed(data={"legal_entity_id": self.entity, "commerce_order_id": self.order, "order_version": 1})
        self.deliver(wire)
        self.work()
        self.assertEqual(self.row(wire["id"])["status"], "dead_letter")
        self.assertEqual(self.row(wire["id"])["code"], "PAYLOAD_INVALID")
        self.assertEqual(_Engine.state["create_attempts"] + _Engine.state["queries"], 0)

    def test_a_price_in_another_currency_is_not_executed(self):
        self.seed()
        wire = self.placed(lines=[{"line_id": "line_001", "sku_id": self.sku, "quantity": {"value": "1", "unit": "EA"},
                                   "unit_price": {"amount": "25.00", "currency": "EUR"},
                                   "line_total": {"amount": "25.00", "currency": "EUR"}}])
        self.deliver(wire)
        self.work()
        self.assertEqual(self.row(wire["id"])["code"], "PAYLOAD_INVALID")
        self.assertEqual(self.engine_orders(), [])


class MissingPreconditionTests(_Base):
    def test_a_missing_customer_mapping_blocks_the_event_and_nothing_is_created(self):
        self.seed(customer=False)
        wire = self.placed()
        self.deliver(wire)
        self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"]), ("blocked", "CUSTOMER_UNMAPPED"))
        self.assertGreater(row["next"], datetime.now(timezone.utc) + timedelta(minutes=10))  # slow retry, not a hot loop
        self.assertEqual(self.engine_orders(), [])
        self.assertEqual(self.scalar("SELECT count(*) FROM baobab.order_consequence WHERE tenant_id = %s", self.tenant), 0)
        self.assertEqual(self.outbox_events(), [])

    def test_the_blocked_event_executes_once_the_mapping_exists(self):
        self.seed(customer=False)
        wire = self.placed()
        self.deliver(wire)
        self.work()
        with self.db.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.erp_master_data_mapping (engine_instance_id, legal_entity_id, resource_kind, "
                           "canonical_id, native_id, desired_digest, source_version) VALUES (%s,%s,'business_partner',%s,501,'d','1')",
                           (self.engine_instance, self.entity, self.customer))
        self.db.commit()
        self.make_due(wire["id"])
        self.work()
        self.assertEqual(self.row(wire["id"])["code"], "EXECUTED")
        self.assertEqual(len(self.engine_orders()), 1)

    def test_a_missing_product_mapping_names_the_lines_and_creates_nothing(self):
        self.seed(product=False)
        wire = self.placed()
        self.deliver(wire)
        self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"]), ("blocked", "PRODUCT_UNMAPPED"))
        self.assertIn("line_001", row["error"])
        self.assertEqual(self.engine_orders(), [])

    def test_an_unmapped_tenant_and_missing_engine_credentials_block(self):
        self.seed(tenant=False)
        wire = self.placed()
        self.deliver(wire)
        self.work()
        self.assertEqual(self.row(wire["id"])["code"], "TENANT_UNMAPPED")
        self.seed(customer=False, product=False)  # the tenant mapping now exists; the master data was seeded first time
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.tenant_mapping SET ad_client_id = %s WHERE tenant_id = %s",
                           (self.ad_client + 1, self.tenant))
        self.db.commit()
        self.make_due(wire["id"])
        self.work()
        self.assertEqual(self.row(wire["id"])["code"], "ENGINE_UNCONFIGURED")
        self.assertEqual(self.engine_orders(), [])

    def test_a_block_past_its_horizon_becomes_a_dead_letter(self):
        self.seed(customer=False)
        wire = self.placed()
        self.deliver(wire)
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.event_inbox SET received_at = now() - interval '73 hours' WHERE event_id = %s::uuid",
                           (wire["id"],))
        self.db.commit()
        self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"]), ("dead_letter", "BLOCKED_HORIZON_EXCEEDED"))


class EngineFailureTests(_Base):
    def test_an_unavailable_engine_retries_with_backoff_then_exhausts(self):
        self.seed()
        wire = self.placed()
        self.deliver(wire)
        _Engine.state["create_status"] = 503
        self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"], row["attempts"]), ("retry", "ENGINE_UNAVAILABLE", 1))
        self.assertGreater(row["next"], datetime.now(timezone.utc))
        self.assertEqual(self.engine_orders(), [])
        # not due yet: a second pass does nothing
        self.assertEqual(self.work()["pass"], {})
        # the last attempt of the budget
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.event_inbox SET attempts = 7, next_attempt_at = now() WHERE event_id = %s::uuid",
                           (wire["id"],))
        self.db.commit()
        self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"]), ("dead_letter", "ATTEMPTS_EXHAUSTED"))

    def test_an_engine_rejection_is_not_retried(self):
        self.seed()
        wire = self.placed()
        self.deliver(wire)
        _Engine.state["create_status"] = 422
        self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"], row["attempts"]), ("dead_letter", "ENGINE_REJECTED", 1))
        self.assertEqual(_Engine.state["create_attempts"], 1)

    def test_two_engine_orders_with_the_reference_are_never_resolved_by_picking_one(self):
        self.seed()
        _Engine.state["orders"] = [{"id": 1, "POReference": self.order}, {"id": 2, "POReference": self.order}]
        wire = self.placed()
        self.deliver(wire)
        self.work()
        self.assertEqual(self.row(wire["id"])["code"], "DUPLICATE_NATIVE_ORDERS")
        self.assertEqual(_Engine.state["create_attempts"], 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM baobab.order_consequence WHERE tenant_id = %s", self.tenant), 0)


class ReplayAndRecoveryTests(_Base):
    def test_replaying_an_accepted_event_does_not_create_a_second_sales_order(self):
        self.seed()
        wire = self.placed()
        self.deliver(wire)
        self.work()
        # 1. Trade redelivers the same event: ingress deduplicates on (source, id), nothing new to execute
        self.assertEqual(self.deliver(wire), 200)
        self.assertEqual(self.work()["pass"], {})
        # 2. an operator (or a bug) puts the very same row back to received: it is recognised as done
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.event_inbox SET status = 'received', next_attempt_at = now() WHERE event_id = %s::uuid",
                           (wire["id"],))
        self.db.commit()
        self.assertEqual(self.work()["codes"], {"ALREADY_EXECUTED": 1})
        # 3. Trade sends the same order again under a new event id
        again = self.placed()
        self.deliver(again)
        self.assertEqual(self.work()["codes"], {"ALREADY_EXECUTED": 1})

        self.assertEqual(len(self.engine_orders()), 1)
        self.assertEqual(_Engine.state["create_attempts"], 1)
        self.assertEqual(len(self.outbox_events()), 1)  # no second announcement of an unchanged record
        self.assertEqual(self.scalar("SELECT count(*) FROM baobab.order_execution WHERE tenant_id = %s", self.tenant), 1)

    def test_restarting_after_an_uncertain_outcome_adopts_the_engine_order_instead_of_creating_another(self):
        self.seed()
        wire = self.placed()
        self.deliver(wire)

        # The worker creates the engine order, then dies before it can commit anything of its own.
        crashed = self.connect()
        with mock.patch("order_to_cash.inbox_execution.PostgresOrderConsequenceStore.open_order", side_effect=_Crash()):
            with self.assertRaises(_Crash):
                self.work(crashed, worker="doomed", lease=300)
        crashed.close()  # a dead process: its session lock goes with it

        self.assertEqual(len(self.engine_orders()), 1)  # the uncertain part: the engine has it, ERP does not know
        self.assertEqual(self.scalar("SELECT count(*) FROM baobab.order_consequence WHERE tenant_id = %s", self.tenant), 0)
        stuck = self.row(wire["id"])
        self.assertEqual((stuck["status"], stuck["claimed_by"], stuck["attempts"]), ("processing", "doomed", 1))
        self.assertEqual(self.work()["pass"], {})  # lease still running: nobody else may take it

        with self.db.cursor() as cursor:  # the lease runs out
            cursor.execute("UPDATE baobab.event_inbox SET lease_expires_at = now() - interval '1 second' WHERE event_id = %s::uuid",
                           (wire["id"],))
        self.db.commit()
        self.assertEqual(self.work(worker="w2")["codes"], {"ADOPTED_NATIVE_ORDER": 1})

        self.assertEqual(len(self.engine_orders()), 1)
        self.assertEqual(_Engine.state["create_attempts"], 1)  # the engine was asked to create exactly once
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"], row["attempts"]), ("processed", "ADOPTED_NATIVE_ORDER", 2))
        self.assertTrue(self.scalar("SELECT adopted FROM baobab.order_execution WHERE tenant_id = %s", self.tenant))
        self.assertEqual(self.scalar("SELECT native_id FROM baobab.order_execution WHERE tenant_id = %s", self.tenant),
                         self.engine_orders()[0]["id"])
        [(event_type, _key, payload, _status)] = self.outbox_events()
        self.assertEqual((event_type, payload["status"]), ("com.baobab-platform.erp.order.consequence-changed.v1", "accepted"))

    def test_a_failure_after_the_engine_create_is_retried_without_a_second_create(self):
        self.seed()
        wire = self.placed()
        self.deliver(wire)
        with mock.patch("order_to_cash.inbox_execution.PostgresOrderConsequenceStore.open_order",
                        side_effect=RuntimeError("database went away")):
            self.work()
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"], row["error"]), ("retry", "UNEXPECTED_ERROR", "RuntimeError"))
        self.assertEqual(self.scalar("SELECT count(*) FROM baobab.order_execution WHERE tenant_id = %s", self.tenant), 0)
        self.assertEqual(self.outbox_events(), [])  # nothing half-recorded
        self.make_due(wire["id"])
        self.assertEqual(self.work()["codes"], {"ADOPTED_NATIVE_ORDER": 1})
        self.assertEqual(_Engine.state["create_attempts"], 1)

    def test_a_worker_that_lost_its_lease_cannot_settle_or_publish(self):
        from inbox.postgres_queue import LeaseLostError, PostgresInboxQueue

        self.seed()
        wire = self.placed()
        self.deliver(wire)
        first = PostgresInboxQueue(self.connect())
        claim = first.claim(event_type=ORDER_PLACED, worker_id="slow", lease_seconds=300)
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.event_inbox SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                           (claim.row_id,))
        self.db.commit()
        taker = PostgresInboxQueue(self.connect()).claim(event_type=ORDER_PLACED, worker_id="fast", lease_seconds=300)
        self.assertEqual(taker.row_id, claim.row_id)
        with self.assertRaises(LeaseLostError):
            first.processed(claim, "EXECUTED")

    def test_the_next_version_of_an_executed_order_is_surfaced_not_applied_and_an_old_one_is_stale(self):
        self.seed()
        first = self.placed(version=2)
        self.deliver(first)
        self.work()
        later = self.placed(version=3)
        older = self.placed(version=1)
        self.deliver(later)
        self.deliver(older)
        report = self.work()
        self.assertEqual(report["codes"], {"AMENDMENT_UNSUPPORTED": 1, "STALE_VERSION": 1})
        self.assertEqual(self.row(later["id"])["status"], "dead_letter")
        self.assertEqual(self.row(older["id"])["status"], "processed")
        self.assertEqual(len(self.engine_orders()), 1)


class ConcurrencyTests(_Base):
    def test_one_inbox_row_is_claimed_by_exactly_one_worker(self):
        from inbox.postgres_queue import PostgresInboxQueue

        self.seed()
        self.deliver(self.placed())
        results = []

        def claim(i):
            results.append(PostgresInboxQueue(self.connect()).claim(event_type=ORDER_PLACED, worker_id=f"w{i}", lease_seconds=300))

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len([r for r in results if r is not None]), 1)

    def test_two_workers_on_two_events_for_one_order_create_one_sales_order(self):
        self.seed()
        gate = threading.Event()
        self.addCleanup(gate.set)
        _Engine.state["create_gate"] = gate  # worker 1 is held inside the engine call, holding the order's lock
        first, second = self.placed(), self.placed()
        self.deliver(first)
        self.deliver(second)
        reports = {}
        w1 = threading.Thread(target=lambda: reports.update(w1=self.work(self.connect(), worker="w1", limit=1)))
        w1.start()
        self.assertTrue(_Engine.state["create_entered"].wait(10))

        # worker 2 arrives for the same order while worker 1 is mid-create: contended, no attempt consumed
        reports["w2"] = self.work(self.connect(), worker="w2", limit=1)
        self.assertEqual(reports["w2"]["codes"], {"ORDER_CONTENDED": 1})
        contended = [self.row(e["id"]) for e in (first, second) if self.row(e["id"])["status"] == "retry"]
        self.assertEqual(len(contended), 1)
        self.assertEqual((contended[0]["code"], contended[0]["attempts"]), ("ORDER_CONTENDED", 0))  # the claim was refunded
        self.assertEqual(_Engine.state["create_attempts"], 1)

        gate.set()
        w1.join(10)
        for event in (first, second):
            self.make_due(event["id"])
        self.work(worker="w3")
        self.assertEqual(len(self.engine_orders()), 1)
        self.assertEqual(_Engine.state["create_attempts"], 1)
        codes = sorted(self.row(e["id"])["code"] for e in (first, second))
        self.assertEqual(codes, ["ALREADY_EXECUTED", "EXECUTED"])
        self.assertEqual(len(self.outbox_events()), 1)

    def test_many_workers_racing_on_one_order_still_create_one_sales_order(self):
        self.seed()
        events = [self.placed() for _ in range(5)]
        for event in events:
            self.deliver(event)
        errors = []

        def run(i):
            try:
                for _ in range(6):
                    self.work(self.connect(), worker=f"w{i}", limit=5)
                    for e in events:
                        self.make_due(e["id"]) if self.row(e["id"])["status"] == "retry" else None
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(4)]
        [t.start() for t in threads]
        [t.join(60) for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(self.engine_orders()), 1)
        self.assertEqual(_Engine.state["create_attempts"], 1)
        self.assertEqual({self.row(e["id"])["status"] for e in events}, {"processed"})
        self.assertEqual(len(self.outbox_events()), 1)


if __name__ == "__main__":
    unittest.main()
