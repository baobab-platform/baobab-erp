import unittest
from datetime import UTC, datetime

from events.envelope import EventEnvelope
from integration.business_partner_adapter import BusinessPartnerProjectionError
from integration.buyer_projection_consumer import (
    BUYER_PROJECTION_REQUESTED,
    consume_buyer_projection,
)


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 100

    def create_record(self, table, fields):
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def update_record(self, table, record_id, fields):
        self.records[(table, record_id)].update(fields)


class FakeMappings:
    def __init__(self):
        self.values = {}

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        return self.values.get((engine_instance_id, legal_entity_id, kind, canonical_id))

    def put(self, *, engine_instance_id, legal_entity_id, kind, canonical_id, native_id, desired_digest, source_version):
        self.values[(engine_instance_id, legal_entity_id, kind, canonical_id)] = (
            native_id,
            desired_digest,
            source_version,
        )


def envelope(**overrides):
    values = dict(
        event_id="f3b3a11b-d767-49c5-a2a8-7ed49d8466f6",
        event_type=BUYER_PROJECTION_REQUESTED,
        schema_version="1.0",
        occurred_at=datetime.now(UTC),
        source="urn:baobab-platform:baobab-trade",
        correlation_id="corr-1",
        tenant_id="tn_zuribeans",
        entity_id="le_zuribeans_za",
        payload={
            "buyer_organisation_id": "buyerorg_1",
            "canonical_organisation_id": "org_buyer_1",
            "display_name": "Cape Coffee Buyers",
            "billing_country": "ZA",
            "default_currency": "ZAR",
            "source_version": "3",
        },
    )
    values.update(overrides)
    return EventEnvelope(**values)


class BuyerProjectionConsumerTests(unittest.TestCase):
    def test_projects_customer_in_explicit_legal_entity(self):
        client, mappings = FakeClient(), FakeMappings()
        result = consume_buyer_projection(
            envelope(),
            engine_instance_id="erp-zuribeans",
            client=client,
            mappings=mappings,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.projection.legal_entity_id, "le_zuribeans_za")
        self.assertEqual(result.projection.source_customer_id, "buyerorg_1")
        self.assertEqual(result.projection.roles, ("customer",))

    def test_replay_reuses_native_business_partner(self):
        client, mappings = FakeClient(), FakeMappings()
        first = consume_buyer_projection(envelope(), engine_instance_id="erp-zuribeans", client=client, mappings=mappings)
        second = consume_buyer_projection(envelope(), engine_instance_id="erp-zuribeans", client=client, mappings=mappings)
        self.assertEqual(first.created, 1)
        self.assertEqual(second.reused, 1)

    def test_rejects_missing_legal_entity_scope(self):
        with self.assertRaises(BusinessPartnerProjectionError):
            consume_buyer_projection(
                envelope(entity_id=""),
                engine_instance_id="erp-zuribeans",
                client=FakeClient(),
                mappings=FakeMappings(),
            )

    def test_ignores_unrelated_event(self):
        result = consume_buyer_projection(
            envelope(event_type="com.baobab-platform.order.accepted.v1"),
            engine_instance_id="erp-zuribeans",
            client=FakeClient(),
            mappings=FakeMappings(),
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
