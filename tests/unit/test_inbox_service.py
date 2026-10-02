import hashlib
import hmac
import json
import unittest

from events import registry
from events.cloudevent import EnvelopeError
from inbox.service import InvalidSignatureError, receive

ORDER_PLACED = "com.baobab-platform.trade.order.placed.v1"


class FakeInboxStore:
    def __init__(self):
        self.seen = set()
        self.recorded = []

    def exists(self, source, event_id):
        return (source, event_id) in self.seen

    def record_received(self, event, data_json):
        self.seen.add(event.dedup_key)
        self.recorded.append((event.dedup_key, data_json))


def _wire(**overrides):
    wire = {
        "specversion": "1.0", "id": "1d032305-669c-45df-b988-01166de4c14c", "type": ORDER_PLACED,
        "source": "urn:baobab-platform:service:trade", "subject": "order:order_01k4n6w5",
        "time": "2026-09-01T10:00:00Z", "datacontenttype": "application/json",
        "dataschema": registry.dataschema_for(ORDER_PLACED), "baobabscope": "tenant",
        "correlationid": "ea733cd4-0daa-4c52-89f8-a940cfa8a1ac", "tenantid": "tn_01k4m7x9q2v6c8r3d5f1h0j4",
        "data": {"commerce_order_id": "order_01k4n6w5"},
    }
    wire.update(overrides)
    return wire


def _signed(wire, secret="secret"):
    body = json.dumps(wire).encode()
    return body, "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class InboxServiceTests(unittest.TestCase):
    def test_records_new_event(self):
        store = FakeInboxStore()
        receive(*_signed(_wire()), "secret", store)
        self.assertEqual(len(store.recorded), 1)

    def test_duplicate_delivery_is_not_reprocessed(self):
        store = FakeInboxStore()
        body, signature = _signed(_wire())
        receive(body, signature, "secret", store)
        receive(body, signature, "secret", store)
        self.assertEqual(len(store.recorded), 1)

    def test_same_id_from_a_different_source_is_a_different_event(self):
        store = FakeInboxStore()
        receive(*_signed(_wire()), "secret", store)
        receive(*_signed(_wire(source="urn:baobab-platform:service:baobab-trade")), "secret", store)
        self.assertEqual(len(store.recorded), 2)

    def test_invalid_signature_is_rejected(self):
        store = FakeInboxStore()
        body, _ = _signed(_wire())
        with self.assertRaises(InvalidSignatureError):
            receive(body, "sha256=wrong", "secret", store)
        self.assertEqual(len(store.recorded), 0)

    def test_legacy_envelope_is_rejected_before_any_write(self):
        store = FakeInboxStore()
        legacy = {"event_id": "evt-1", "event_type": "trade.order.accepted", "schema_version": "1.0",
                  "occurred_at": "2026-08-30T12:00:00Z", "source": "baobab-trade", "correlation_id": "c",
                  "tenant_id": "t", "entity_id": "E", "payload": {}}
        with self.assertRaises(EnvelopeError):
            receive(*_signed(legacy), "secret", store)
        self.assertEqual(store.recorded, [])

    def test_unregistered_type_is_rejected(self):
        store = FakeInboxStore()
        with self.assertRaises(EnvelopeError):
            receive(*_signed(_wire(type="com.baobab-platform.trade.order.cancelled.v1")), "secret", store)
        self.assertEqual(store.recorded, [])

    def test_non_json_body_is_a_value_error(self):
        store = FakeInboxStore()
        body = b"not json"
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        with self.assertRaises(ValueError):
            receive(body, signature, "secret", store)


if __name__ == "__main__":
    unittest.main()
