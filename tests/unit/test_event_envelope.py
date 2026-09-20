import unittest
from datetime import UTC

from events.envelope import EventEnvelope


class EventEnvelopeTests(unittest.TestCase):
    def valid_event(self):
        return {
            "event_id": "evt-1",
            "event_type": "erp.purchase-order.completed.v1",
            "schema_version": "1.0",
            "occurred_at": "2026-08-30T12:00:00Z",
            "source": "baobab-erp",
            "correlation_id": "cor-1",
            "tenant_id": "tenant-1",
            "entity_id": "THAMANI-GLOBAL",
            "payload": {},
        }

    def test_parses_timezone_aware_timestamp(self):
        event = EventEnvelope.from_dict(self.valid_event())
        self.assertEqual(event.occurred_at.tzinfo, UTC)

    def test_rejects_missing_context(self):
        value = self.valid_event()
        del value["tenant_id"]
        with self.assertRaisesRegex(ValueError, "tenant_id"):
            EventEnvelope.from_dict(value)

    def test_rejects_naive_timestamp(self):
        value = self.valid_event()
        value["occurred_at"] = "2026-08-30T12:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            EventEnvelope.from_dict(value)

    def test_parses_shared_cloudevent(self):
        event = EventEnvelope.from_dict(
            {
                "specversion": "1.0",
                "id": "f3b3a11b-d767-49c5-a2a8-7ed49d8466f6",
                "type": "com.baobab-platform.customer.buyer-erp-projection.requested.v1",
                "source": "urn:baobab-platform:baobab-trade",
                "time": "2026-09-20T12:00:00Z",
                "correlationid": "cor-1",
                "tenantid": "tn_zuribeans",
                "entityid": "le_zuribeans_za",
                "data": {"buyer_organisation_id": "buyerorg_1"},
            }
        )
        self.assertEqual(event.event_type, "com.baobab-platform.customer.buyer-erp-projection.requested.v1")
        self.assertEqual(event.entity_id, "le_zuribeans_za")
        self.assertEqual(event.payload["buyer_organisation_id"], "buyerorg_1")


if __name__ == "__main__":
    unittest.main()
