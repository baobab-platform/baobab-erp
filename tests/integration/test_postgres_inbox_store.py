import hashlib
import hmac
import json
import unittest
import uuid

import psycopg

from events import registry
from events.cloudevent import EnvelopeError
from inbox.postgres_store import PostgresInboxStore
from inbox.service import InvalidSignatureError, receive

from _postgres import connect

SECRET = "secret"
ORDER_PLACED = "com.baobab-platform.trade.order.placed.v1"
TRADE = "urn:baobab-platform:service:trade"


class PostgresInboxStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.event_id = str(uuid.uuid4())
        self.tenant_id = f"tn_{uuid.uuid4().hex[:16]}"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.event_inbox WHERE event_id = %s::uuid", (self.event_id,))
        self.connection.commit()
        self.connection.close()

    def _wire(self, **overrides):
        wire = {
            "specversion": "1.0", "id": self.event_id, "type": ORDER_PLACED, "source": TRADE,
            "subject": "order:order_01k4n6w5", "time": "2026-09-06T12:00:00Z",
            "datacontenttype": "application/json", "dataschema": registry.dataschema_for(ORDER_PLACED),
            "baobabscope": "tenant", "correlationid": str(uuid.uuid4()), "tenantid": self.tenant_id,
            "causationid": str(uuid.uuid4()), "idempotencykey": "trade-order-order_01k4n6w5-v1",
            "data": {"commerce_order_id": "order_01k4n6w5"},
        }
        wire.update(overrides)
        return wire

    def _signed(self, wire):
        body = json.dumps(wire).encode()
        return body, "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    def _count(self, source=None):
        with self.connection.cursor() as cursor:
            if source:
                cursor.execute("SELECT count(*) FROM baobab.event_inbox WHERE event_id = %s::uuid AND ce_source = %s",
                               (self.event_id, source))
            else:
                cursor.execute("SELECT count(*) FROM baobab.event_inbox WHERE event_id = %s::uuid", (self.event_id,))
            return cursor.fetchone()[0]

    def test_receive_persists_every_envelope_member(self):
        store = PostgresInboxStore(self.connection)
        wire = self._wire()
        receive(*self._signed(wire), SECRET, store)

        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, envelope_format, event_type, tenant_id, ce_source, ce_subject, ce_dataschema, ce_scope,"
                " ce_correlation_id::text, ce_causation_id::text, ce_idempotency_key, payload_json"
                " FROM baobab.event_inbox WHERE event_id = %s::uuid", (self.event_id,))
            row = cursor.fetchone()
        self.assertEqual(row, ("received", "cloudevents", ORDER_PLACED, self.tenant_id, TRADE, wire["subject"],
                               wire["dataschema"], "tenant", wire["correlationid"], wire["causationid"],
                               wire["idempotencykey"], wire["data"]))

    def test_duplicate_delivery_does_not_insert_twice(self):
        store = PostgresInboxStore(self.connection)
        body, signature = self._signed(self._wire())
        receive(body, signature, SECRET, store)
        receive(body, signature, SECRET, store)
        self.assertEqual(self._count(), 1)

    def test_deduplication_key_is_source_and_id_not_id_alone(self):
        store = PostgresInboxStore(self.connection)
        receive(*self._signed(self._wire()), SECRET, store)
        receive(*self._signed(self._wire(source="urn:baobab-platform:service:baobab-trade")), SECRET, store)
        self.assertEqual(self._count(), 2)
        self.assertEqual((self._count(TRADE), self._count("urn:baobab-platform:service:baobab-trade")), (1, 1))

    def test_database_uniqueness_backs_the_service_check(self):
        store = PostgresInboxStore(self.connection)
        receive(*self._signed(self._wire()), SECRET, store)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO baobab.event_inbox (event_id, event_type, tenant_id, payload_json, envelope_format,"
                    " ce_source, ce_subject, ce_dataschema, ce_scope, ce_correlation_id, ce_time)"
                    " VALUES (%s::uuid, %s, %s, '{}'::jsonb, 'cloudevents', %s, 's', 'https://x/y', 'tenant',"
                    " %s::uuid, now())", (self.event_id, ORDER_PLACED, self.tenant_id, TRADE, str(uuid.uuid4())))
        self.connection.rollback()

    def test_invalid_signature_is_rejected_before_any_write(self):
        store = PostgresInboxStore(self.connection)
        body, _ = self._signed(self._wire())
        with self.assertRaises(InvalidSignatureError):
            receive(body, "sha256=wrong", SECRET, store)
        self.assertEqual(self._count(), 0)

    def test_legacy_and_unregistered_events_leave_no_row(self):
        store = PostgresInboxStore(self.connection)
        legacy = {"event_id": self.event_id, "event_type": "trade.order.accepted", "schema_version": "1.0",
                  "occurred_at": "2026-09-06T12:00:00Z", "source": "baobab-trade", "correlation_id": "cor-1",
                  "tenant_id": "tenant-1", "entity_id": "THAMANI-GLOBAL", "payload": {}}
        with self.assertRaises(EnvelopeError):
            receive(*self._signed(legacy), SECRET, store)
        with self.assertRaises(EnvelopeError):
            receive(*self._signed(self._wire(type="com.baobab-platform.trade.order.cancelled.v1")), SECRET, store)
        self.assertEqual(self._count(), 0)


if __name__ == "__main__":
    unittest.main()
