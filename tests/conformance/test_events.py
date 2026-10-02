import json
import unittest
import uuid

import _shared as shared
from events import registry
from events.cloudevent import CloudEvent, EnvelopeError, check_consumable, new_event

ENVELOPE = shared.schema_uri("events/v1/envelope.schema.json")
# The one registered ERP event with no example in Shared: a payload built from its schema's required members.
BUYER_PROFILE = "com.baobab-platform.customer.buyer-commercial-profile.changed.v1"


def _examples():
    return {p.name: json.loads(p.read_text()) for p in sorted((shared.CONTRACTS / "erp/v1/examples").glob("*.json"))}


class EventConformanceTests(unittest.TestCase):
    def test_every_example_is_valid_against_the_envelope_and_its_registered_dataschema(self):
        examples = _examples()
        self.assertGreaterEqual(len(examples), 9)
        for name, wire in examples.items():
            with self.subTest(name):
                self.assertEqual(shared.errors(ENVELOPE, wire), [])
                self.assertEqual(shared.errors(wire["dataschema"], wire["data"]), [])
                event = CloudEvent.from_wire(wire)
                self.assertEqual(event.to_wire(), wire)  # nothing is lost or invented by ERP's model
                self.assertEqual(wire["dataschema"], registry.dataschema_for(wire["type"]))

    def test_every_erp_produced_example_is_buildable_by_new_event_and_stays_valid(self):
        produced = {w["type"]: w for w in _examples().values() if w["type"] in registry.PRODUCED}
        for event_type, wire in produced.items():
            with self.subTest(event_type):
                event = new_event(
                    type=event_type, subject=wire["subject"], correlation_id=wire["correlationid"],
                    data=wire["data"], tenant_id=wire["tenantid"], causation_id=wire.get("causationid"),
                    idempotency_key=wire.get("idempotencykey"))
                self.assertEqual(shared.errors(ENVELOPE, event.to_wire()), [])
                self.assertEqual(shared.errors(event.dataschema, event.data), [])
                self.assertEqual(event.source, wire["source"])  # ERP identifies itself as the examples do

    def test_the_order_consequence_event_erp_builds_is_valid_against_the_envelope_and_its_payload_schema(self):
        from datetime import datetime, timezone
        from order_to_cash.consequence import OrderConsequence
        from order_to_cash.consequence_events import consequence_changed_event
        order = str(uuid.uuid4())
        for status, accounting, inventory, invoice in (("accepted", "pending", "pending", None),
                                                        ("posted", "posted", "fulfilled", "erp_inv12345")):
            with self.subTest(status):
                record = OrderConsequence("tn_01k4m7x9q2v6c8r3d5f1h0j4", order, "ZURIBEANS", 2, "erp_abc12345", status,
                                          accounting, inventory, 3, datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
                                          invoice_id=invoice)
                event = consequence_changed_event(record, None)
                self.assertEqual(shared.errors(ENVELOPE, event.to_wire()), [])
                self.assertEqual(shared.errors(event.dataschema, event.data), [])
                self.assertEqual(CloudEvent.from_wire(event.to_wire()), event)

    def test_all_seven_erp_event_types_are_covered_by_examples(self):
        covered = {w["type"] for w in _examples().values()}
        self.assertEqual({t for t in registry.PRODUCED if t.startswith("com.baobab-platform.erp.")} - covered, set())

    def test_the_buyer_profile_event_validates_against_its_fragment_schema(self):
        uri = registry.PRODUCED[BUYER_PROFILE]
        data = {"buyer_organisation_id": None, "tenant_id": "tn_01k4m7x9q2v6c8r3d5f1h0j4", "source_system": "ERP",
                "credit_status": "APPROVED", "currency_code": "UGX", "as_of": "2026-09-01T10:00:00Z"}
        data["buyer_organisation_id"] = "buyerorg_01k4m7x9q2v6c8r3d5f1h0j4"  # ^(buyerorg|b2borg)_[a-z0-9]+$
        self.assertEqual(shared.errors(uri, data), [])
        event = new_event(type=BUYER_PROFILE, subject="buyer:" + data["buyer_organisation_id"],
                          correlation_id=str(uuid.uuid4()), data=data, tenant_id=data["tenant_id"])
        self.assertEqual(shared.errors(ENVELOPE, event.to_wire()), [])
        self.assertEqual(shared.errors(event.dataschema, event.data), [])

    def test_legacy_shape_is_rejected_by_shared_and_by_erp(self):
        legacy = shared.read_json("events/v1/compatibility/legacy-trade-erp-event.json")
        self.assertNotEqual(shared.errors(ENVELOPE, legacy), [])
        with self.assertRaises(EnvelopeError):
            CloudEvent.from_wire(legacy)

    def test_consumed_examples_are_accepted_by_the_inbox_guard(self):
        consumed = [w for w in _examples().values() if w["type"] in registry.CONSUMED]
        self.assertEqual({w["type"] for w in consumed}, set(registry.CONSUMED))
        for wire in consumed:
            with self.subTest(wire["type"]):
                check_consumable(CloudEvent.from_wire(wire))

    def test_erp_cannot_emit_what_it_does_not_own(self):
        owned = self._registry_entries("baobab-erp")
        self.assertEqual(owned, set(registry.PRODUCED))
        for event_type in self._registry_entries("baobab-trade") | self._registry_entries("baobab-iam"):
            with self.assertRaises(EnvelopeError, msg=event_type):
                new_event(type=event_type, subject="x:1", correlation_id=str(uuid.uuid4()), data={}, tenant_id=None)

    def test_registry_index_matches_shared_for_consumed_events(self):
        trade_owned = self._registry_entries("baobab-trade")
        for event_type, (_, producer) in registry.CONSUMED.items():
            self.assertEqual(producer, "baobab-trade")
            self.assertIn(event_type, trade_owned)

    def test_every_registered_erp_type_is_active_and_its_asyncapi_exists(self):
        text = shared.read_text("events/v1/event-registry.yaml")
        entries = shared.read_yaml("events/v1/event-registry.yaml")
        rows = entries["events"] if isinstance(entries, dict) and "events" in entries else entries
        for row in rows:
            if row.get("producer") == "baobab-erp":
                self.assertEqual(row["lifecycle"], "ACTIVE", row["type"])
                self.assertTrue((shared.ROOT / row["asyncapi"]).is_file(), row["asyncapi"])
        self.assertIn("producer: baobab-erp", text)

    def test_delivery_identity_is_source_and_id(self):
        policy = shared.read_yaml("idempotency/v1/policy.yaml")
        self.assertEqual(policy["events"]["delivery_identity"], ["source", "id"])
        self.assertEqual(policy["events"]["command_consequence"]["envelope_attribute"], "idempotencykey")
        event = new_event(type="com.baobab-platform.erp.invoice.changed.v1", subject="invoice:1",
                          correlation_id=str(uuid.uuid4()), data={}, tenant_id="tn_abc123")
        self.assertEqual(event.dedup_key, (event.source, event.id))

    @staticmethod
    def _registry_entries(producer: str) -> set[str]:
        entries = shared.read_yaml("events/v1/event-registry.yaml")
        rows = entries["events"] if isinstance(entries, dict) and "events" in entries else entries
        return {row["type"] for row in rows if row.get("producer") == producer}


if __name__ == "__main__":
    unittest.main()
