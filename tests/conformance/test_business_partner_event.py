"""erp.business-partner.changed against the pinned Shared contracts (ERP-CAP-08)."""
import unittest
import uuid
from datetime import datetime, timezone

import _shared as shared
from customers.partner_events import EVENT, business_partner_changed_event
from events import registry

ENVELOPE = shared.schema_uri("events/v1/envelope.schema.json")


def build(**overrides):
    values = dict(tenant_id="tn_01k4m7x9q2v6c8r3d5f1h0j4", legal_entity_id="ZURIBEANS", business_partner_id="erp_" + "a1" * 8,
                  source_customer_id="customer_001", display_name="Example Importer", status="active", revision=1,
                  now=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc), correlation_id=None)
    values.update(overrides)
    return business_partner_changed_event(**values)


class BusinessPartnerEventTests(unittest.TestCase):
    def test_every_status_validates_against_the_envelope_and_the_registered_payload_schema(self):
        for status in ("active", "suspended", "closed"):
            with self.subTest(status):
                wire = build(status=status).to_wire()
                self.assertEqual(shared.errors(ENVELOPE, wire), [])
                self.assertEqual(shared.errors(wire["dataschema"], wire["data"]), [])
                self.assertEqual(wire["dataschema"], registry.dataschema_for(EVENT))

    def test_identity_is_a_function_of_the_partner_and_revision_and_a_correlation_is_never_invented_per_call(self):
        first, again, next_revision = build(), build(), build(revision=2)
        self.assertEqual((first.id, first.correlationid), (again.id, again.correlationid))
        self.assertNotEqual(first.id, next_revision.id)
        self.assertEqual(build(correlation_id=str(uuid.UUID(int=7))).correlationid, str(uuid.UUID(int=7)))

    def test_trade_only_attributes_are_not_claimed(self):
        self.assertNotIn("billing_country", build().data)
        self.assertNotIn("default_currency", build().data)
