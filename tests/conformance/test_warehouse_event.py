"""erp.warehouse.changed against the pinned Shared contracts (ERP-CAP-08)."""
import unittest
import uuid
from datetime import datetime, timezone

import _shared as shared
from events import registry
from provisioning.warehouse_events import EVENT, warehouse_changed_event

ENVELOPE = shared.schema_uri("events/v1/envelope.schema.json")


def build(**overrides):
    values = dict(tenant_id="tn_01k4m7x9q2v6c8r3d5f1h0j4", legal_entity_id="ZURIBEANS-UG", warehouse_id="erp_" + "b2" * 8, code="KLA",
                  name="KLA", country="UG", timezone="Africa/Kampala", status="active", revision=1,
                  now=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc), correlation_id=None)
    values.update(overrides)
    return warehouse_changed_event(**values)


class WarehouseEventTests(unittest.TestCase):
    def test_both_statuses_validate_against_the_envelope_and_the_registered_payload_schema(self):
        for status in ("active", "inactive"):
            with self.subTest(status):
                wire = build(status=status).to_wire()
                self.assertEqual(shared.errors(ENVELOPE, wire), [])
                self.assertEqual(shared.errors(wire["dataschema"], wire["data"]), [])
                self.assertEqual(wire["dataschema"], registry.dataschema_for(EVENT))

    def test_the_payload_carries_the_public_id_and_the_declared_timezone_only(self):
        data = build().data
        self.assertEqual(data["warehouse_id"], "erp_" + "b2" * 8)
        self.assertEqual(data["timezone"], "Africa/Kampala")
        self.assertEqual(set(data), {"legal_entity_id", "warehouse_id", "code", "name", "country", "timezone", "status", "revision"})

    def test_identity_is_a_function_of_the_warehouse_and_revision(self):
        first, again, later = build(), build(), build(revision=2)
        self.assertEqual((first.id, first.idempotencykey), (again.id, again.idempotencykey))
        self.assertNotEqual(first.id, later.id)
        self.assertEqual(build(correlation_id=str(uuid.UUID(int=9))).correlationid, str(uuid.UUID(int=9)))
