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

## Accounting outcomes: `invoice.changed` and `payment.accounting-changed`

Produced (ERP-CAP-05/08) from facts read back from the engine after the native process ran, never from the request: invoice number,
total and currency (ISO code and the currency's own precision), and whether the engine reports the invoice completed and paid. An
invoice or payment the engine has not completed is not announced, and neither is an invoice with no commerce-order link (the
contract requires one). `outstanding` and `due_on` are optional and ERP does not hold them (the engine computes them), so they are
omitted rather than guessed.

Statuses: invoice `posted` on posting, `partially_paid` / `paid` after an allocation (paid is the engine's `IsPaid`); payment
`posted` on completion, `allocated` when the engine reports the payment fully allocated (`IsAllocated`, which counts every allocation, so a payment split across invoices is judged on its total), otherwise `partially_allocated` after an allocation. A document's status only moves forward: a retried completion never re-announces an allocated payment or paid invoice as posted.
`baobab.document_outcome` (migration 0022) holds each document's revision, advanced only when status or the observed facts change, in
the same transaction as the outbox row; so a retried request announces nothing twice. Event ids are derived from tenant, document
and revision; idempotency keys are `erp-invoice-{id}-r{revision}` and `erp-payment-{capture id}-r{revision}`. `issued_at` is when ERP
first observed the posting, `accounted_at` when it observed that revision. If the read-back fails the request fails and rolls back,
like every other engine error; if the facts are absent or inconsistent no event is built.

The legacy-shaped rows the order-to-cash steps record are still stored as `held` beside the
canonical event and are never delivered.

## `business-partner.changed` (ERP-CAP-08)

Produced by the customer executor, in the same transaction as the mapping and the inbox outcome, each time ERP changes the partner it
holds for a Trade customer (created, adopted or updated with different content). Identity has three separate parts and none replaces
another: `source_customer_id` is the Trade customer id (the canonical source reference); `business_partner_id` is an `erp_` public id
minted at this boundary, stored in `baobab.erp_master_data_mapping.erp_resource_id` when the mapping is first written (migration 0023,
which also backfills existing rows by their own row, never by name) and never changed by an update, retry or restart; the iDempiere
record id stays private to the engine instance and never appears in the event.

`revision` counts published changes of the partner (`baobab.document_outcome`, type `business_partner`), not the Trade version: a new
Trade version with unchanged content publishes nothing, and a replay or a stale version publishes nothing. Roles are `["customer"]`,
the only role a customer projection establishes. `billing_country` and `default_currency` are Trade's and ERP does not hold them for
the partner, so they are omitted. `status` is the one ERP applied (the engine itself records only active or inactive, so
suspended versus closed is ERP's record of what it applied, not an engine fact). A partner mapped before migration 0023 has an id but
announces nothing until its next change.

Still not produced: `warehouse.changed` (the payload requires a `timezone` no ERP source holds, the declaration has no timezone, and
warehouse creation is split across two unconverged paths), `inventory.availability-changed` (no engine change signal; ERP only
answers reads) and `buyer-commercial-profile.changed` (ERP holds no credit facts yet).

## Executing `trade.order.placed` (inbox worker)

`POST /events/inbound` verifies the signature, the registered type, producer and `dataschema`, and records the event durably;
it executes nothing. `modules/application/inbox_worker.py` (service `baobab-inbox-worker`) claims due `trade.order.placed` rows and
runs each to an outcome (`modules/order_to_cash/inbox_execution.py`). The same worker executes `trade.customer.projected` (see
"Executing `trade.customer.projected`" below), claiming customers first in every pass so a customer that arrives with its first order is a
business partner, and mapped, before the order is looked at.

Per event, in one pass: read the payload (`placed_order.py`) -> resolve the tenant's engine placement and the customer and every
SKU through explicit master-data mappings -> take the per-order lock -> look the order up in the engine by `POReference` (the
Trade order id) and create it only if absent -> in **one transaction** write the consequence record
(`baobab.order_consequence`, status `accepted`), the order link (`baobab.order_execution`), the registered
`order.consequence-changed` event (outbox) and the inbox outcome. The event is then delivered by the dispatch worker like any other
outbox row, and is the same record `GET /order-consequences/{id}` serves.

| Inbox status | Meaning | Next |
|---|---|---|
| `received` | stored at ingress | claimed when due |
| `processing` | claimed under a lease (`BAOBAB_INBOX_LEASE_SECONDS`) | settled, or re-claimed when the lease expires (worker crash) |
| `retry` | transient failure (`ENGINE_UNAVAILABLE`, `UNEXPECTED_ERROR`, `ORDER_CONTENDED`) | backoff 30 s doubling to a 1 h ceiling (reached at the 8th attempt); dead letter `ATTEMPTS_EXHAUSTED` after 24 attempts, roughly 17 hours. `ORDER_CONTENDED` (another worker holds the order) refunds its attempt |
| `blocked` | a precondition is missing: `TENANT_UNMAPPED`, `CUSTOMER_UNMAPPED`, `PRODUCT_UNMAPPED`, `ENGINE_UNCONFIGURED`, `ENGINE_ORG_MISMATCH` (the credentials are for another AD_Org than the tenant mapping; AD_Org 0 means the whole AD_Client) | retried every 15 min until 72 h after receipt, then dead letter `BLOCKED_HORIZON_EXCEEDED`. Nothing is created or invented; fix the mapping and it proceeds |
| `processed` | `EXECUTED`, `ADOPTED_NATIVE_ORDER` (found by reference after an uncertain attempt), `ALREADY_EXECUTED`, `STALE_VERSION` | done |
| `dead_letter` | `PAYLOAD_INVALID`, `ENGINE_REJECTED` (HTTP 400/422), `DUPLICATE_NATIVE_ORDERS`, `UNIT_MISMATCH` (a line's unit is not the product's own X12 unit; there is no conversion), `AMENDMENT_UNSUPPORTED` (a later `order_version` of an executed order), `TENANT_MISSING`, plus the two exhausted codes | an operator; `last_error` holds a fixed reason, never payload content |

Why a replay or a restart cannot create a second sales order: an order has at most one row in `baobab.order_consequence` and
`baobab.order_execution` (primary key tenant + Trade order); a session advisory lock per order serialises workers while the engine
is touched; and creating the engine order and committing ERP's rows cannot be one transaction, so a worker that dies in between
leaves an engine order carrying the `POReference`, which the next attempt adopts instead of creating another. More than one match
is never resolved by choosing; it is `DUPLICATE_NATIVE_ORDERS`. Settling a row is fenced on the lease, so a worker that lost it
rolls back everything it wrote.

## Executing `trade.customer.projected` (same worker)

`modules/customers/projection_execution.py` turns an accepted customer event into a business partner (`C_BPartner`) and writes the
master-data mapping (`baobab.erp_master_data_mapping`, kind `business_partner`, canonical id = the Trade `customer_id`) that order
execution resolves its customer through. Until it existed an order for a customer nobody had mapped by hand was blocked as
`CUSTOMER_UNMAPPED`.

Per event: read the payload (`customers/payload.py`) -> resolve the tenant's engine placement -> take the per-customer lock -> compare the
version with the mapping -> create the partner (or update it, or adopt one an earlier attempt created) -> in **one transaction** write the
mapping and the inbox outcome. The partner is created with `Value` = the Trade customer id, `Name` = `display_name`, `IsCustomer`, `IsActive`
(true only for status `active`) and the client's default business-partner group; a suspended or closed customer becomes an inactive partner
and is never deleted. Not projected: tax registration references (the contract carries no raw values) and billing country / preferred
currency (a partner has no such field; they belong to locations and price lists).

| Outcome | Code | Meaning |
|---|---|---|
| `processed` | `CREATED`, `UPDATED`, `ADOPTED_NATIVE_PARTNER` (found by its marker after an uncertain attempt, then brought to this version) | done |
| `processed` | `ALREADY_PROJECTED` (same version again), `STALE_VERSION` (older than the mapped one) | nothing written |
| `retry` | `ENGINE_UNAVAILABLE`, `UNEXPECTED_ERROR`, `CUSTOMER_CONTENDED` (another worker holds the customer; refunds its attempt) | same backoff as orders |
| `blocked` | `TENANT_UNMAPPED`, `ENGINE_UNCONFIGURED`, `ENGINE_ORG_MISMATCH`, `BP_GROUP_UNAVAILABLE` (the client has no, or more than one, default business-partner group) | retried every 15 min until 72 h after receipt |
| `dead_letter` | `PAYLOAD_INVALID`, `TENANT_MISSING`, `ENGINE_REJECTED`, `VERSION_CONFLICT` (the same version with different content), `DUPLICATE_NATIVE_PARTNERS` (more than one partner carries the marker), `NATIVE_PARTNER_MISSING` (mapped, but gone from the engine), plus the two exhausted codes | an operator |

The marker is `baobab-customer:<tenant>:<legal entity>:<customer id>`, written to the partner's `Description`; an uncertain create is
recovered by finding that marker, never by matching a name or search key, so two tenants' partners can not be mistaken for each other.
Limits: this has run against a fake engine, not a live iDempiere. `Description` as the marker column, the default-group lookup and the
written fields are what a live run must confirm, and `Value` is limited by the engine's search-key length (a longer Trade id is refused as
`ENGINE_REJECTED`).

To retry a dead letter once its cause is fixed: `UPDATE baobab.event_inbox SET status = 'received', attempts = 0, next_attempt_at = now(), outcome_code = NULL, last_error = NULL WHERE id = <row>` (it is then executed again under the same guards, so an order that did get created is recognised, not repeated).

Placement precondition: the worker resolves the engine placement from `baobab.tenant_mapping.engine_instance_id` (as do the master-data mappings and the inventory read). The provisioning `PERSIST_MAPPING` step now writes it from the plan (`engine_instance_id` in the step payload) and refuses to write a mapping without one; migration 0020 filled rows written earlier where the provisioning records name exactly one instance. A row it could not fill (no provisioning record, or records that disagree) still blocks as `TENANT_UNMAPPED`; an operator sets it deliberately: `UPDATE baobab.tenant_mapping SET engine_instance_id = '<ei_...>' WHERE tenant_id = '<tn_...>' AND entity_id = '<LEGAL-ENTITY>' AND engine_instance_id IS NULL`. Provisioning steps are applied by `baobab-provisioning-worker` (ERP-CAP-04, `docs/operations.md`); tenants provisioned before it existed were mapped outside the application.

Limits, stated plainly: this has run against a fake engine, not a live iDempiere (`POReference` as the lookup column is
unconfirmed there). It creates the draft sales order and the `accepted` consequence; completing the order, shipment and invoice
remain the existing explicit endpoints. Order amendments (a higher `order_version`) are surfaced, not applied. An order that
the older `POST /sales-orders` endpoint created without an `order_version` has no consequence record and carries no `POReference`,
so an event for it would create a second engine order; do not mix the two paths for one order. The workers need a direct
Postgres connection (the order lock is session-level).

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
