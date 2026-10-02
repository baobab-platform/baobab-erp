import unittest
import uuid
from datetime import UTC, datetime

from events import registry
from events.cloudevent import CloudEvent, EnvelopeError, check_consumable, new_event

TENANT = "tn_01k4m7x9q2v6c8r3d5f1h0j4"
ORDER_PLACED = "com.baobab-platform.trade.order.placed.v1"


def trade_wire(**overrides):
    """A Trade-produced inbound event, shaped like Shared's erp/v1/examples/commerce-order-placed.json."""
    wire = {
        "specversion": "1.0", "id": str(uuid.uuid4()), "type": ORDER_PLACED,
        "source": "urn:baobab-platform:service:trade", "subject": "order:order_01k4n6w5",
        "time": "2026-09-01T10:00:00Z", "datacontenttype": "application/json",
        "dataschema": registry.dataschema_for(ORDER_PLACED), "baobabscope": "tenant",
        "correlationid": str(uuid.uuid4()), "tenantid": TENANT,
        "idempotencykey": "trade-order-order_01k4n6w5-v1", "data": {"commerce_order_id": "order_01k4n6w5"},
    }
    wire.update(overrides)
    return wire


def erp_event(**overrides):
    args = dict(type="com.baobab-platform.erp.order.consequence-changed.v1", subject="order:order_01k4n6w5",
                correlation_id=str(uuid.uuid4()), data={"status": "posted"}, tenant_id=TENANT)
    args.update(overrides)
    return new_event(**args)


class CloudEventWireTests(unittest.TestCase):
    def test_round_trips_the_canonical_wire_form(self):
        wire = trade_wire()
        self.assertEqual(CloudEvent.from_wire(wire).to_wire(), wire)

    def test_wire_omits_absent_optional_members_and_renders_utc_z(self):
        event = erp_event(time=datetime(2026, 10, 2, 12, 0, 1, tzinfo=UTC))
        wire = event.to_wire()
        self.assertEqual(wire["time"], "2026-10-02T12:00:01Z")
        for name in ("causationid", "idempotencykey", "traceparent", "tracestate"):
            self.assertNotIn(name, wire)
        self.assertEqual(wire["specversion"], "1.0")
        self.assertEqual(wire["datacontenttype"], "application/json")

    def test_dedup_key_is_source_and_id(self):
        event = erp_event()
        self.assertEqual(event.dedup_key, (registry.ERP_SOURCE, event.id))

    def test_legacy_shape_is_rejected_not_coerced(self):
        legacy = {"event_id": "01K4EVENT", "event_type": "trade.order.accepted", "schema_version": "1.0",
                  "occurred_at": "2026-08-30T12:00:00Z", "source": "baobab-trade", "correlation_id": "c",
                  "tenant_id": "t", "entity_id": "E", "payload": {}}
        with self.assertRaisesRegex(EnvelopeError, "unknown envelope members"):
            CloudEvent.from_wire(legacy)

    def test_invalid_members_are_rejected(self):
        cases = {
            "unknown member": dict(extra="x"),
            "bad specversion": dict(specversion="0.3"),
            "non-uuid id": dict(id="evt-1"),
            "nabhold namespace": dict(type="com.nabhold.trade.order.placed.v1"),
            "unversioned type": dict(type="com.baobab-platform.trade.order.placed"),
            "relative source": dict(source="baobab-trade"),
            "empty subject": dict(subject=""),
            "naive time": dict(time="2026-09-01T10:00:00"),
            "wrong content type": dict(datacontenttype="text/xml"),
            "bad scope": dict(baobabscope="global"),
            "non-uuid correlation": dict(correlationid="corr-1"),
            "short idempotency key": dict(idempotencykey="short"),
            "bad traceparent": dict(traceparent="00-zz-b7ad6b7169203331-01"),
            "null optional": dict(causationid=None),
            "non-object data": dict(data=[1]),
        }
        for name, overrides in cases.items():
            with self.subTest(name), self.assertRaises(EnvelopeError):
                CloudEvent.from_wire(trade_wire(**overrides))

    def test_missing_required_members_are_named(self):
        wire = trade_wire()
        del wire["dataschema"]
        with self.assertRaisesRegex(EnvelopeError, "dataschema"):
            CloudEvent.from_wire(wire)

    def test_tenant_scope_rule(self):
        no_tenant = trade_wire()
        del no_tenant["tenantid"]
        with self.assertRaisesRegex(EnvelopeError, "requires tenantid"):
            CloudEvent.from_wire(no_tenant)
        with self.assertRaisesRegex(EnvelopeError, "must not carry tenantid"):
            CloudEvent.from_wire(trade_wire(baobabscope="platform"))
        with self.assertRaisesRegex(EnvelopeError, "canonical tenant"):
            CloudEvent.from_wire(trade_wire(tenantid="tenant-1"))
        platform = trade_wire(baobabscope="platform")
        del platform["tenantid"]
        self.assertEqual(CloudEvent.from_wire(platform).baobabscope, "platform")


class ProducedEventTests(unittest.TestCase):
    def test_every_registered_type_can_be_produced_with_its_registry_dataschema(self):
        for event_type, dataschema in registry.PRODUCED.items():
            event = erp_event(type=event_type)
            self.assertEqual(event.dataschema, dataschema)
            self.assertEqual(event.source, registry.ERP_SOURCE)

    def test_no_second_vocabulary(self):
        for legacy in ("erp.sales-order.accepted.v1", "erp.payment.completed.v1",
                       "com.baobab-platform.erp.sales-order.accepted.v1",
                       "com.baobab-platform.trade.order.placed.v1"):  # a Trade type is not ERP's to emit
            with self.subTest(legacy), self.assertRaises(EnvelopeError):
                erp_event(type=legacy)

    def test_platform_scope_when_no_tenant(self):
        event = erp_event(tenant_id=None)
        self.assertEqual((event.baobabscope, event.tenantid), ("platform", None))

    def test_optional_context_is_carried(self):
        cause = str(uuid.uuid4())
        event = erp_event(causation_id=cause, idempotency_key="trade-order-order_01k4n6w5-v1",
                          traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        wire = event.to_wire()
        self.assertEqual((wire["causationid"], wire["idempotencykey"]), (cause, "trade-order-order_01k4n6w5-v1"))


class ConsumedEventTests(unittest.TestCase):
    def consume(self, **overrides):
        return check_consumable(CloudEvent.from_wire(trade_wire(**overrides)))

    def test_accepts_a_registered_trade_event_with_either_producer_spelling(self):
        self.assertEqual(self.consume().type, ORDER_PLACED)
        self.consume(source="urn:baobab-platform:service:baobab-trade")

    def test_rejects_unregistered_types_wrong_schema_wrong_source(self):
        with self.assertRaisesRegex(EnvelopeError, "not an event type"):
            self.consume(type="com.baobab-platform.trade.order.cancelled.v1")
        with self.assertRaisesRegex(EnvelopeError, "dataschema"):
            self.consume(dataschema="https://contracts.baobab-platform.com/erp/v1/invoice-outcome.schema.json")
        with self.assertRaisesRegex(EnvelopeError, "producer"):
            self.consume(source="urn:baobab-platform:service:baobab-pulse")

    def test_rejects_a_platform_scoped_trade_event(self):
        wire = trade_wire(baobabscope="platform")
        del wire["tenantid"]
        with self.assertRaisesRegex(EnvelopeError, "tenant-scoped"):
            check_consumable(CloudEvent.from_wire(wire))

    def test_erp_own_events_are_not_consumable(self):
        with self.assertRaises(EnvelopeError):
            check_consumable(erp_event())


if __name__ == "__main__":
    unittest.main()
