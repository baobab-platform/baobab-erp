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

## Produced from the order-consequence read model

`com.baobab-platform.erp.order.consequence-changed.v1` is produced whenever the order-consequence read model changes
(`modules/order_to_cash/consequence_events.py`): when ERP opens a record for an order, and whenever an observed fact (order
completed, shipment completed, invoice posted) changes it. The payload is the read model's contract document, so the event and
`GET /order-consequences/{commerce_order_id}` are two projections of one record and cannot disagree. It is recorded in the same
transaction as the change, and a repeated fact (which changes nothing) announces nothing. The event id is derived from
(tenant, order, revision), so a revision is announced once however often its transaction is retried; the idempotency key is
`erp-order-consequence-{commerce_order_id}-r{revision}`. A correlation id that is not a UUID is replaced by one derived from the
order, so related events share a correlation without inventing one per call.

Still not produced: `invoice.changed` and `payment.accounting-changed`. Their registered payloads need facts ERP does not hold yet
(invoice number, total and due date; payment amount and capture id), and ERP does not invent them; they follow once those facts
are recorded as ERP-owned projections. The legacy-shaped rows the order-to-cash steps record are still stored as `held` beside the
canonical event and are never delivered.

## Delivery

`modules/outbox.service.dispatch_pending` drains pending/retry canonical rows through an `EventTransport`;
`modules/integration.delivery_transport.deliver` is the concrete webhook transport: structured mode
(`Content-Type: application/cloudevents+json`), signed with `modules/security.signing.sign_body`. Failed
deliveries retry with exponential backoff (`outbox.service.backoff_seconds`, capped at one hour) up to
`outbox.service.MAX_ATTEMPTS` before moving to a dead-letter state. `time` is serialised as RFC 3339 UTC (`Z`).

### provisioning.changed and signed delivery (FB-04)

`com.baobab-platform.erp.provisioning.changed.v1` is announced for **every committed revision** of a provisioning command,
recorded in the outbox in the same transaction as the change (`provisioning.command_store`: `accept` writes revision 1,
`advance` every later one, and `PostgresProvisioningStore.set_status` projects an entity's status into its command through
`provisioning.command_state.derive` in the transaction that changed it). Its identity is a function of the change:
`id` is the version 5 UUID of `urn:baobab-platform:event:erp-provisioning:{operation_id}:{revision}` and the idempotency key is
`erp-provisioning-{operation_id}-r{revision}`, so a redelivery is the same event and a consumer deduplicates by (source, id).
The data is exactly what `GET /provisioning-operations/{operation_id}` answers, and a failure carries the fixed code
`ERP_PROVISIONING_FAILED`, never an entity's error text. The event is a trigger to inspect authoritative state, not the state.

It is delivered to the Control Plane event ingress over **signed delivery** (`integration.signed_delivery`; Shared
`events/v1/signed-delivery.schema.json`): headers `Baobab-Key-Id`, `Baobab-Timestamp` and `Baobab-Signature`
(`hmac-sha256=<hex>` over the recipient, key id, timestamp and body digest), signed afresh on every attempt, never following a
redirect, https only (http for a local address). A 202 `ACCEPTED` or 200 `DUPLICATE` receipt that names this event's id is a
delivery; 400, 409, 413 and 422 dead-letter at once; anything else retries with backoff (`next_attempt_at`) until 72 hours after
the event was recorded, then dead-letters (`outbox.service.RetryPolicy`). Delivery is at-least-once. Every other event type
still goes to the legacy webhook, unchanged, and `provisioning.changed` never does.

`modules/outbox/postgres_store.py` and `modules/inbox/postgres_store.py` are the real backing stores
(`modules/application/dispatch_worker.py` wires the former to delivery); `tests/integration/` exercises
record -> dispatch -> deliver -> mark-delivered and receive -> verify -> deduplicate -> persist against a live
PostgreSQL database.
