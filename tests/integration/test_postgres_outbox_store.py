import unittest
import uuid
from datetime import UTC, datetime

import psycopg

from events.cloudevent import CloudEvent, EnvelopeError, new_event
from events.envelope import EventEnvelope
from outbox.postgres_store import PostgresOutboxStore
from outbox.service import dispatch_pending

from _postgres import connect


class _FailingTransport:
    def deliver(self, event):
        raise ConnectionError("simulated destination failure")


class _RecordingTransport:
    def __init__(self):
        self.delivered = []

    def deliver(self, event):
        self.delivered.append(event)


class PostgresOutboxStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.tenant_id = f"tn_{uuid.uuid4().hex[:16]}"
        self.event_ids: list[str] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.event_outbox WHERE event_id = ANY(%s::uuid[])", (self.event_ids,))
        self.connection.commit()
        self.connection.close()

    def _event(self, **overrides):
        args = dict(type="com.baobab-platform.erp.payment.accounting-changed.v1", subject="payment:pay-1",
                    correlation_id=str(uuid.uuid4()), data={"amount": 42}, tenant_id=self.tenant_id)
        args.update(overrides)
        event = new_event(**args)
        self.event_ids.append(event.id)
        return event

    def _row(self, event_id, columns="status"):
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT {columns} FROM baobab.event_outbox WHERE event_id = %s::uuid", (event_id,))
            return cursor.fetchone()

    def test_record_then_dispatch_delivers_the_canonical_event_and_marks_delivered(self):
        store = PostgresOutboxStore(self.connection)
        event = self._event(causation_id=str(uuid.uuid4()), idempotency_key="trade-order-order_01-v1",
                            traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        store.record_event(event)
        self.connection.commit()

        transport = _RecordingTransport()
        dispatch_pending(store, transport)

        mine = [e for e in transport.delivered if e.id == event.id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].to_wire(), event.to_wire())  # every envelope member survives storage
        self.assertEqual(self._row(event.id), ("delivered",))

    def test_platform_scoped_event_is_stored_without_a_tenant(self):
        store = PostgresOutboxStore(self.connection)
        event = self._event(tenant_id=None)
        store.record_event(event)
        self.connection.commit()
        self.assertEqual(self._row(event.id, "ce_scope, tenant_id"), ("platform", None))

    def test_failed_delivery_increments_attempts_and_retries(self):
        store = PostgresOutboxStore(self.connection)
        event = self._event()
        store.record_event(event)
        self.connection.commit()

        dispatch_pending(store, _FailingTransport())

        status, attempts, last_error = self._row(event.id, "status, attempts, last_error")
        self.assertEqual((status, attempts), ("retry", 1))
        self.assertIn("simulated destination failure", last_error)

    def test_only_registered_erp_events_can_be_recorded(self):
        store = PostgresOutboxStore(self.connection)
        foreign = CloudEvent.from_wire({
            "specversion": "1.0", "id": str(uuid.uuid4()), "type": "com.baobab-platform.trade.order.placed.v1",
            "source": "urn:baobab-platform:service:trade", "subject": "order:o1",
            "time": "2026-09-01T10:00:00Z", "datacontenttype": "application/json",
            "dataschema": "https://contracts.baobab-platform.com/erp/v1/commerce-order-consequence.schema.json",
            "baobabscope": "tenant", "correlationid": str(uuid.uuid4()), "tenantid": self.tenant_id, "data": {}})
        with self.assertRaises(EnvelopeError):
            store.record_event(foreign)

    def test_legacy_domain_event_is_held_and_never_delivered(self):
        store = PostgresOutboxStore(self.connection)
        legacy_id = str(uuid.uuid4())
        self.event_ids.append(legacy_id)
        store.record(EventEnvelope(
            event_id=legacy_id, event_type="erp.payment.completed.v1", schema_version="1.0",
            occurred_at=datetime.now(UTC), source="baobab-erp", correlation_id="cor-1",
            tenant_id=self.tenant_id, entity_id="THAMANI-GLOBAL", payload={"amount": 7}))
        self.connection.commit()

        self.assertEqual(self._row(legacy_id), ("held",))
        transport = _RecordingTransport()
        dispatch_pending(store, transport)
        self.assertEqual([e for e in transport.delivered if e.id == legacy_id], [])
        self.assertGreaterEqual(store.held_count(), 1)

    def test_database_refuses_a_half_formed_row_of_either_format(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO baobab.event_outbox (event_id, event_type, payload_json, occurred_at,"
                    " envelope_format) VALUES (%s::uuid, 'com.baobab-platform.erp.invoice.changed.v1', '{}'::jsonb,"
                    " now(), 'cloudevents')", (str(uuid.uuid4()),))
        self.connection.rollback()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO baobab.event_outbox (event_id, event_type, payload_json, occurred_at)"
                    " VALUES (%s::uuid, 'erp.x.v1', '{}'::jsonb, now())", (str(uuid.uuid4()),))
        self.connection.rollback()


if __name__ == "__main__":
    unittest.main()
