"""The dispatcher routes provisioning.changed to the Control Plane event ingress over signed delivery and everything else to the
legacy webhook (FB-04b), against real Postgres and a local ingress."""
import base64
import contextlib
import io
import json
import os
import unittest
import unittest.mock
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from application import dispatch_worker
from events.cloudevent import new_event
from integration import signed_delivery as sd
from outbox.postgres_store import PostgresOutboxStore

from _postgres import connect

SECRET = bytes(range(32))
KEY_ID = "erp-delivery-2026-10"


class _Ingress(BaseHTTPRequestHandler):
    received: list = []
    status = 202

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).received.append((dict(self.headers), body))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"event_id": json.loads(body)["id"], "status": "ACCEPTED", "received_at": "2026-10-07T17:30:00Z"}).encode())

    def log_message(self, *_):
        pass


class _Webhook(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        type(self).received.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_):
        pass


class DispatchWorkerTests(unittest.TestCase):
    def setUp(self):
        _Ingress.received, _Ingress.status = [], 202
        self.server = HTTPServer(("127.0.0.1", 0), _Ingress)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.connection = connect()
        self.tenant = f"tn_{uuid.uuid4().hex[:16]}"
        self.ids = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.event_outbox WHERE event_id = ANY(%s::uuid[])", (self.ids,))
        self.connection.commit()
        self.connection.close()

    def record(self, type_, subject):
        event = new_event(type=type_, subject=subject, correlation_id=str(uuid.uuid4()), data={"revision": 1}, tenant_id=self.tenant)
        self.ids.append(event.id)
        PostgresOutboxStore(self.connection).record_event(event)
        self.connection.commit()
        return event

    def run_worker(self, **env):
        base = {"DATABASE_URL": os.environ["DATABASE_URL"]}
        for name in ("BAOBAB_CP_EVENT_INGRESS_URL", "BAOBAB_CP_EVENT_KEY_ID", "BAOBAB_CP_EVENT_SECRET_B64",
                     "BAOBAB_WEBHOOK_URL", "BAOBAB_EVENT_SIGNING_SECRET"):
            base[name] = ""
        out = io.StringIO()
        with unittest.mock.patch.dict(os.environ, {**base, **env}), contextlib.redirect_stdout(out):
            dispatch_worker.main()
        return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    def signed_env(self):
        return {"BAOBAB_CP_EVENT_INGRESS_URL": f"http://127.0.0.1:{self.server.server_port}/v1/integration/events",
                "BAOBAB_CP_EVENT_KEY_ID": KEY_ID, "BAOBAB_CP_EVENT_SECRET_B64": base64.b64encode(SECRET).decode()}

    def status_of(self, event):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT status FROM baobab.event_outbox WHERE event_id = %s::uuid", (event.id,))
            return cursor.fetchone()[0]

    def test_provisioning_changed_is_delivered_signed_and_nothing_else_goes_to_the_ingress(self):
        provisioning = self.record("com.baobab-platform.erp.provisioning.changed.v1", "provisioning:p1")
        payment = self.record("com.baobab-platform.erp.payment.accounting-changed.v1", "payment:pay-1")
        report, = self.run_worker(**self.signed_env())
        self.assertEqual(report["destination"], "control-plane-ingress")
        self.assertEqual(self.status_of(provisioning), "delivered")
        self.assertEqual(self.status_of(payment), "pending", "another type waits for its own destination, it does not fail")
        mine = [(h, b) for h, b in _Ingress.received if json.loads(b)["id"] == provisioning.id]
        self.assertEqual(len(mine), 1)
        headers, body = mine[0]
        self.assertTrue(sd.verify({KEY_ID: sd.DeliveryKey(KEY_ID, SECRET)}, "baobab-control-plane", headers, body,
                                  datetime.now(timezone.utc)))
        self.assertEqual([json.loads(b)["id"] for _, b in _Ingress.received if json.loads(b)["id"] == payment.id], [])

    def test_with_both_destinations_each_event_goes_to_exactly_one(self):
        _Webhook.received = []
        webhook = HTTPServer(("127.0.0.1", 0), _Webhook)
        Thread(target=webhook.serve_forever, daemon=True).start()
        self.addCleanup(webhook.shutdown)
        self.addCleanup(webhook.server_close)
        provisioning = self.record("com.baobab-platform.erp.provisioning.changed.v1", "provisioning:p4")
        payment = self.record("com.baobab-platform.erp.payment.accounting-changed.v1", "payment:pay-2")
        reports = self.run_worker(**self.signed_env(), BAOBAB_WEBHOOK_URL=f"http://127.0.0.1:{webhook.server_port}/hook",
                                  BAOBAB_EVENT_SIGNING_SECRET="s" * 32)
        self.assertEqual([r["destination"] for r in reports], ["control-plane-ingress", "webhook"])
        self.assertEqual((self.status_of(provisioning), self.status_of(payment)), ("delivered", "delivered"))
        self.assertEqual([e["id"] for e in _Webhook.received if e["id"] in (provisioning.id, payment.id)], [payment.id],
                         "provisioning.changed never goes to the legacy webhook")
        self.assertEqual([json.loads(b)["id"] for _, b in _Ingress.received if json.loads(b)["id"] in (provisioning.id, payment.id)],
                         [provisioning.id])

    def test_provisioning_changed_is_never_sent_to_the_legacy_webhook_even_when_it_is_the_only_destination(self):
        _Webhook.received = []
        webhook = HTTPServer(("127.0.0.1", 0), _Webhook)
        Thread(target=webhook.serve_forever, daemon=True).start()
        self.addCleanup(webhook.shutdown)
        self.addCleanup(webhook.server_close)
        provisioning = self.record("com.baobab-platform.erp.provisioning.changed.v1", "provisioning:p5")
        payment = self.record("com.baobab-platform.erp.payment.accounting-changed.v1", "payment:pay-3")
        report, = self.run_worker(BAOBAB_WEBHOOK_URL=f"http://127.0.0.1:{webhook.server_port}/hook", BAOBAB_EVENT_SIGNING_SECRET="s" * 32)
        self.assertEqual(report["destination"], "webhook")
        self.assertEqual((self.status_of(provisioning), self.status_of(payment)), ("pending", "delivered"))
        self.assertEqual([e["id"] for e in _Webhook.received if e["id"] in (provisioning.id, payment.id)], [payment.id])

    def test_the_report_names_the_backlog_and_a_dead_letter_is_visible(self):
        event = self.record("com.baobab-platform.erp.provisioning.changed.v1", "provisioning:p2")
        _Ingress.status = 422
        report, = self.run_worker(**self.signed_env())
        self.assertEqual((report["delivered"], report["retried"], report["dead_lettered"]), (0, 0, 1))
        self.assertGreaterEqual(report["dead_letter"], 1)
        self.assertEqual(self.status_of(event), "dead_letter")

    def test_a_transient_failure_is_retried_later_not_dead_lettered(self):
        event = self.record("com.baobab-platform.erp.provisioning.changed.v1", "provisioning:p3")
        _Ingress.status = 503
        report, = self.run_worker(**self.signed_env())
        self.assertEqual((report["retried"], report["dead_lettered"]), (1, 0))
        self.assertEqual(self.status_of(event), "retry")
        again, = self.run_worker(**self.signed_env())  # not due yet: backoff is real
        self.assertEqual((again["delivered"], again["retried"]), (0, 0))

    def test_a_partial_or_missing_destination_configuration_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "no event destination"):
            self.run_worker()
        with self.assertRaisesRegex(RuntimeError, "must be set together"):
            self.run_worker(BAOBAB_CP_EVENT_INGRESS_URL="https://control.example.com/v1/integration/events")
        with self.assertRaises(sd.DeliveryConfigurationError):
            self.run_worker(**{**self.signed_env(), "BAOBAB_CP_EVENT_SECRET_B64": base64.b64encode(b"short").decode()})


if __name__ == "__main__":
    unittest.main()
