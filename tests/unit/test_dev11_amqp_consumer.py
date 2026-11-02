"""DEV-11 native AMQP receipt contract: ACK only after durable inbox admission."""
import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace

from application.amqp_consumer import (
    EVENT_CONTENT_TYPE, EVENT_SIGNATURE_HEADER, RejectedEvent,
    admit, delivery_callback, validate_connection_url,
)
from events import registry


class Store:
    def __init__(self):
        self.seen = set()
        self.rows = []

    def exists(self, source, event_id):
        return (source, event_id) in self.seen

    def record_received(self, event, data):
        self.seen.add((event.source, event.id))
        self.rows.append((event.source, event.id, data))


class Scope:
    def __init__(self, store, *, fails=False):
        self.store = store
        self.fails = fails

    def __enter__(self):
        if self.fails:
            raise ConnectionError("test-database-offline")
        return self.store

    def __exit__(self, *args):
        return False


class Channel:
    def __init__(self):
        self.calls = []
        self.stopped = False

    def basic_ack(self, **kw):
        self.calls.append(("ACK", kw))

    def basic_nack(self, **kw):
        self.calls.append(("NACK", kw))

    def basic_reject(self, **kw):
        self.calls.append(("REJECT", kw))

    def stop_consuming(self):
        self.stopped = True


def event_wire():
    return {
        "specversion": "1.0",
        "id": "1d032305-669c-45df-b988-01166de4c14c",
        "type": "com.baobab-platform.trade.order.placed.v1",
        "source": "urn:baobab-platform:service:trade",
        "subject": "order:order_01k4n6w5",
        "time": "2026-09-01T10:00:00Z",
        "datacontenttype": "application/json",
        "dataschema": registry.dataschema_for("com.baobab-platform.trade.order.placed.v1"),
        "baobabscope": "tenant",
        "tenantid": "tn_01k4m7x9q2v6c8r3d5f1h0j4",
        "correlationid": "ea733cd4-0daa-4c52-89f8-a940cfa8a1ac",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "data": {"commerce_order_id": "order_01k4n6w5"},
    }


def signed(wire, secret):
    raw = json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()
    return raw, "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class DEV11AMQPAdmissionTests(unittest.TestCase):
    secret = "dev11-signing-secret-this-is-synthetic"

    def setUp(self):
        self.store = Store()
        self.channel = Channel()
        self.delivery = SimpleNamespace(delivery_tag=7)

    def call(self, wire=None, *, signature=None, content_type=EVENT_CONTENT_TYPE, fails=False):
        body, valid = signed(wire or event_wire(), self.secret)
        props = SimpleNamespace(
            content_type=content_type,
            headers={EVENT_SIGNATURE_HEADER: signature if signature is not None else valid},
        )
        return delivery_callback(
            self.channel, self.delivery, props, body,
            store_factory=lambda: Scope(self.store, fails=fails),
            secret=self.secret,
        )

    def test_signed_registered_event_is_admitted_then_acked(self):
        self.call()
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.channel.calls, [("ACK", {"delivery_tag": 7})])

    def test_redelivery_ack_does_not_create_second_receipt(self):
        self.call()
        self.call()
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(len(self.channel.calls), 2)
        self.assertTrue(all(action == "ACK" for action, _ in self.channel.calls))

    def test_forged_signature_rejected_to_existing_dlx(self):
        self.call(signature="sha256=" + "0" * 64)
        self.assertFalse(self.store.rows)
        self.assertEqual(self.channel.calls,
                         [("REJECT", {"delivery_tag": 7, "requeue": False})])

    def test_unregistered_event_rejected(self):
        self.call(wire={**event_wire(), "type": "com.baobab-platform.trade.unknown.v1"})
        self.assertFalse(self.store.rows)
        self.assertEqual(self.channel.calls[0][0], "REJECT")

    def test_content_type_denied(self):
        self.call(content_type="application/json")
        self.assertFalse(self.store.rows)
        self.assertEqual(self.channel.calls[0][0], "REJECT")

    def test_broker_not_acked_when_postgres_unavailable(self):
        with self.assertRaisesRegex(RuntimeError, "ERP_AMQP_ADMISSION_BLOCKED"):
            self.call(fails=True)
        self.assertEqual(self.channel.calls,
                         [("NACK", {"delivery_tag": 7, "requeue": True})])
        self.assertTrue(self.channel.stopped)

    def test_oversized_event_denied_before_db(self):
        with self.assertRaises(RejectedEvent):
            admit(b"x" * (1024 * 1024 + 1), "sha256=123",
                  EVENT_CONTENT_TYPE, self.store, self.secret)

    def test_transport_tls_is_nonnegotiable_outside_disposable_lab(self):
        for environment in ("staging", "production"):
            with self.assertRaisesRegex(RuntimeError, "ERP_AMQP_TLS_REQUIRED"):
                validate_connection_url("amqp://user:password@broker/private", environment)
        self.assertEqual(
            validate_connection_url("amqps://user:password@broker/private", "production"),
            "amqps://user:password@broker/private",
        )

if __name__ == "__main__":
    unittest.main()
