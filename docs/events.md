# Canonical Events

Per ADR-ERP-006, ERP events:

- describe meaningful business facts and use only event types registered in Shared
  (`contracts/events/v1/event-registry.yaml`), e.g. `com.baobab-platform.erp.order.consequence-changed.v1`.
  `modules/events/registry.py` is ERP's index of the types it produces and consumes;
- use canonical Baobab identity, never an iDempiere native ID;
- carry explicit context (`tenantid` for a tenant event, none for a platform event, `correlationid`);
- are recorded transactionally through `modules/outbox` before being published;
- support at-least-once delivery -- consumers deduplicate on `(source, id)` (`modules/inbox`);
- evolve through the versioned type (`...v1`) and the payload schema named in `dataschema`.

## Envelope

The envelope is the CloudEvents 1.0 structured profile in Shared
(`contracts/events/v1/envelope.schema.json`), implemented by `modules/events/cloudevent.py::CloudEvent`:
required members, a closed member set (the legacy ERP/Trade shape is rejected, not coerced), UUID `id` and
`correlationid`, the `com.baobab-platform.*.vN` type grammar, the tenant-scope rule, idempotency key and W3C
trace context. `new_event()` builds ERP-produced events and refuses any type ERP does not own, so there is no
second vocabulary; `check_consumable()` admits only registered Trade types with their registered `dataschema`
and producer.

`tests/contract/test_shared_event_examples.py` parses every example in a Shared checkout
(`SHARED_CONTRACTS_DIR`) and checks the registry index against Shared's event registry.

## Legacy events

`modules/events/envelope.py::EventEnvelope` is the pre-CloudEvents internal shape. It is still the input of
ERP's own domain recorders (order-to-cash, `/outbox/record`), which store it as `held` in
`baobab.event_outbox`: kept, visible (`PostgresOutboxStore.held_count`), never delivered. Shared archives that
shape as rejected and no registered canonical event exists yet for those facts (their payloads also carry
iDempiere native ids). They are delivered only once an outcome projection maps them to registered events with
canonical payloads.

## Delivery

`modules/outbox.service.dispatch_pending` drains pending/retry canonical rows through an `EventTransport`;
`modules/integration.delivery_transport.deliver` is the concrete webhook transport: structured mode
(`Content-Type: application/cloudevents+json`), signed with `modules/security.signing.sign_body`. Failed
deliveries retry with exponential backoff (`outbox.service.backoff_seconds`, capped at one hour) up to
`outbox.service.MAX_ATTEMPTS` before moving to a dead-letter state. `time` is serialised as RFC 3339 UTC (`Z`).

`modules/outbox/postgres_store.py` and `modules/inbox/postgres_store.py` are the real backing stores
(`modules/application/dispatch_worker.py` wires the former to delivery); `tests/integration/` exercises
record -> dispatch -> deliver -> mark-delivered and receive -> verify -> deduplicate -> persist against a live
PostgreSQL database.
