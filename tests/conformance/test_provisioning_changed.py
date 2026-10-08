"""provisioning.changed and signed delivery against the pinned Shared contracts (FB-04, Shared#249).

The event's identity is a function of the committed change, and signed delivery is the one HTTPS binding for it. Both are proven
against the real files at the pin: the example's id is reproduced by ERP's own function, the event ERP builds validates against
the envelope and the payload schema it names, and every header set ERP produces validates against the closed delivery schema."""
import hashlib
import hmac
import json
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

import _shared as shared
from events import registry
from integration import signed_delivery as sd
from provisioning import command_events

ENVELOPE = shared.schema_uri("events/v1/envelope.schema.json")
DELIVERY = shared.schema_uri("events/v1/signed-delivery.schema.json")
VECTOR_SIGNATURE = "f8fb9e93e325a379d3692202629c81bc8f94654521bb6f5073e12b324ae3adea"
EXAMPLE = json.loads(shared.read_text("erp/v1/examples/provisioning-changed.json"))


@dataclass(frozen=True)
class Record:
    operation_id: str
    tenant_id: str
    legal_entity_ids: tuple
    state: str
    revision: int
    updated_at: datetime
    failure_code: str | None = None


def _record_of(wire: dict) -> Record:
    data = wire["data"]
    return Record(data["operation_id"], data["tenant_id"], tuple(data["legal_entity_ids"]), data["state"], data["revision"],
                  datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")), data.get("failure_code"))


class ProvisioningChangedConformanceTests(unittest.TestCase):
    def test_erps_function_reproduces_the_shared_examples_identity(self):
        event = command_events.provisioning_changed(_record_of(EXAMPLE))
        self.assertEqual(event.id, EXAMPLE["id"])
        self.assertEqual(event.idempotencykey, EXAMPLE["idempotencykey"])
        self.assertEqual(event.subject, EXAMPLE["subject"])
        self.assertEqual(event.data, EXAMPLE["data"])

    def test_the_event_erp_builds_is_valid_against_the_envelope_and_its_payload_schema(self):
        for state, code in (("accepted", None), ("active", None), ("failed", "ERP_PROVISIONING_FAILED")):
            record = Record("1d5a1ea4-6355-4ca2-b851-4ebde6847035", "tn_01k4m7x9q2v6c8r3d5f1h0j4", ("ZURIBEANS",), state, 3,
                            datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc), code)
            with self.subTest(state):
                wire = command_events.provisioning_changed(record).to_wire()
                self.assertEqual(shared.errors(ENVELOPE, wire), [])
                self.assertEqual(shared.errors(wire["dataschema"], wire["data"]), [])
                self.assertEqual(wire["type"], command_events.EVENT_TYPE)
                self.assertEqual(wire["dataschema"], registry.dataschema_for(command_events.EVENT_TYPE))

    def test_one_event_per_revision_and_the_same_revision_is_the_same_event(self):
        first = _record_of(EXAMPLE)
        again = command_events.provisioning_changed(first)
        self.assertEqual(sd.event_body(again), sd.event_body(command_events.provisioning_changed(first)))
        later = Record(**{**first.__dict__, "revision": first.revision + 1})
        self.assertNotEqual(command_events.provisioning_changed(later).id, again.id)
        self.assertNotEqual(command_events.provisioning_changed(later).idempotencykey, again.idempotencykey)
        # The correlation id is the operation's, so every revision of an operation shares it.
        self.assertEqual(command_events.provisioning_changed(later).correlationid, again.correlationid)

    def test_the_event_registry_names_erp_as_the_one_producer(self):
        entries = {e["type"]: e for e in yaml.safe_load(shared.read_text("events/v1/event-registry.yaml"))["events"]}
        self.assertEqual(entries[command_events.EVENT_TYPE]["producer"], "baobab-erp")
        self.assertEqual(entries[command_events.EVENT_TYPE]["lifecycle"], "ACTIVE")


class SignedDeliveryConformanceTests(unittest.TestCase):
    KEY = sd.DeliveryKey("erp-delivery-2026-10", bytes(range(32)))

    def test_the_headers_erp_produces_validate_against_the_closed_delivery_schema(self):
        body = sd.event_body(command_events.provisioning_changed(_record_of(EXAMPLE)))
        headers = sd.headers_for(self.KEY, "baobab-control-plane", body, datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc))
        self.assertEqual(shared.errors(shared.schema_uri("events/v1/signed-delivery.schema.json", "/$defs/DeliveryHeaders"), headers), [])

    def test_the_delivery_constants_are_the_ones_shared_pins(self):
        policy = json.loads(shared.read_text("events/v1/signed-delivery.schema.json"))["$defs"]["SenderPolicy"]["properties"]
        self.assertEqual(int(sd.REPLAY_WINDOW.total_seconds()), policy["replay_window_seconds"]["const"])
        self.assertEqual(sd.MIN_SECRET_BYTES, policy["minimum_secret_bytes"]["const"])
        self.assertEqual(sd.MAX_BODY_BYTES, policy["max_body_bytes"]["const"])
        self.assertEqual(sorted(sd.PERMANENT_STATUSES), policy["permanent_failure_statuses"]["const"])

    def test_the_dispatchers_horizon_is_the_one_shared_pins_and_below_receipt_retention(self):
        from application.dispatch_worker import SIGNED_POLICY
        policy = json.loads(shared.read_text("events/v1/signed-delivery.schema.json"))["$defs"]["SenderPolicy"]["properties"]
        self.assertEqual(SIGNED_POLICY.horizon.total_seconds() / 3600, policy["max_retry_horizon_hours"]["const"])
        self.assertLess(SIGNED_POLICY.horizon.total_seconds(), policy["receipt_retention_days"]["const"] * 86400)

    def test_the_signing_string_and_signature_are_the_documented_ones(self):
        # A fixed vector the Control Plane's ingress must reproduce exactly (docs/architecture/signed-event-delivery.md).
        key = sd.DeliveryKey("erp-delivery-2026-10", bytes(range(32)))
        body = b'{"specversion":"1.0"}'
        digest = hashlib.sha256(body).hexdigest()
        text = sd.signing_string("baobab-control-plane", key.key_id, "2026-10-07T17:30:00Z", body)
        self.assertEqual(text, f"baobab-event-delivery-v1\nbaobab-control-plane\nerp-delivery-2026-10\n2026-10-07T17:30:00Z\n{digest}".encode())
        expected = "hmac-sha256=" + hmac.new(key.secret, text, hashlib.sha256).hexdigest()
        self.assertEqual(sd.sign(key, "baobab-control-plane", "2026-10-07T17:30:00Z", body), expected)
        self.assertEqual(expected, "hmac-sha256=" + VECTOR_SIGNATURE)
