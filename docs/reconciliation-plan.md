# Reconciliation Plan: baobab-erp vs. nabhold/shared

## Why this document exists

`nabhold/zuribeans` and `nabhold/thamani` are waiting on baobab-erp for integrations
to take shape. An audit of that readiness found that baobab-erp's own internal
wiring (OSGi bundles, context/mapping resolution, outbox/inbox) is solid and
tested, but baobab-erp's *contracts* -- the event envelope shape, the HTTP boundary
API, and the mapping/provisioning data model -- predate and have drifted from
`nabhold/shared`'s now-published, canonical `contracts/erp/v1` and
`contracts/events/v1` packages. `nabhold/shared`'s own ADR-0005 names baobab-erp as
a required implementer of `contracts/erp/v1`.

This document is the phased plan for closing that drift. `contracts.lock.yaml`
(repo root) pins the exact `nabhold/shared` commit and contract versions this plan
was written against, mirroring how `nabhold/baobab-trade` tracks the same
repository -- see that file for per-contract notes on baobab-erp's current drift.

**Important framing**: `nabhold/baobab-trade` -- the actual downstream consumer in
the dependency chain -- has not integrated `contracts/erp/v1` either (no adapter
code exists in its tree yet). So there is no live traffic today that baobab-erp's
current implementation is breaking. This is forward-looking readiness work, not an
active incident, and `nabhold/shared`'s own single-consumer rule (a contract
shouldn't be treated as final/load-bearing until it has a second real consumer)
counsels against racing ahead of Trade to build speculative, untested vendor
mappings. Each phase below says explicitly what it's blocked on.

## Phase 1 -- Event envelope: CloudEvents 1.0

**Target**: `contracts/events/v1/envelope.schema.json` (CloudEvents 1.0 structured
JSON profile). Required fields: `specversion` (const `"1.0"`), `id` (uuid, paired
with `source` as the delivery-dedup key), `type` (reverse-DNS + version, pattern
`^com\.nabhold\.[a-z0-9]+(?:[.-][a-z0-9]+)*\.v[1-9][0-9]*$`), `source` (stable URI,
no hostname/tenant), `subject`, `time`, `datacontenttype` (const
`application/json`), `dataschema` (URI into a real payload schema), `baobabscope`
(`platform`|`tenant`, drives whether `tenantid` is required via the schema's
`if`/`then`), `correlationid`, `data`. Optional: `causationid`, `tenantid`,
`idempotencykey`, `traceparent`, `tracestate`.

**Current shape**: `modules/events/envelope.py`'s `EventEnvelope` (9 fields:
`event_id, event_type, schema_version, occurred_at, source, correlation_id,
tenant_id, entity_id, payload`) is exactly the shape `nabhold/shared` itself
archives as legacy
(`contracts/events/v1/compatibility/legacy-trade-erp-event.json`). Note an
existing *internal* drift worth fixing as part of this phase either way:
`contracts/events/envelope.schema.json` (baobab-erp's own, self-declared schema)
already declares an optional `causation_id`, but the dataclass has no such field
and neither reads nor writes it anywhere.

**Files this phase touches**: `modules/events/envelope.py` (field rewrite),
`contracts/events/envelope.schema.json` (replace with, or point at, the real
schema), a new `db/migrations/000N_*.sql` reshaping `baobab.event_outbox` /
`baobab.event_inbox` columns, `modules/outbox/service.py`,
`modules/outbox/postgres_store.py`, `modules/inbox/service.py`,
`modules/inbox/postgres_store.py`, `modules/integration/delivery_transport.py`
(`_to_wire_dict`), `modules/application/dispatch_worker.py`,
`modules/application/server.py`'s `/events/inbound` handler (dedup key becomes
`(source, id)` per `contracts/idempotency/v1/policy.yaml`, not just `event_id`),
and the 9 tests that already reference the envelope or mapping tables:
`tests/contract/test_envelope_examples.py`, `tests/unit/test_event_envelope.py`,
`tests/unit/test_delivery_transport.py`, `tests/unit/test_outbox_service.py`,
`tests/unit/test_identity_reconciliation.py`,
`tests/integration/test_postgres_context_store.py`,
`tests/integration/test_postgres_outbox_store.py`,
`tests/integration/test_postgres_mapping_store.py`,
`tests/integration/test_http_server.py`.

**Blocked on**: real `data` payloads. Setting `type`/`dataschema` to a genuine
`com.nabhold.erp.*` value and a real `contracts/erp/v1/*.schema.json` URI while
the underlying payload is still baobab-erp's own placeholder shape would be worse
than today's honest, self-declared envelope -- it would claim conformance the
payload doesn't have. So this phase's *wrapper* work (fields, dedup key, DB
columns) can proceed independently, but wiring real `type`/`dataschema`/`data`
values is gated on Phase 2 (canonical ids) and effectively on Phase 4.

**Done when**: `EventEnvelope` round-trips every required/optional field above;
outbox/inbox dedup on `(source, id)`; existing tests updated and passing against a
real Postgres database, same discipline as today.

## Phase 2 -- Mapping/provisioning data model

> **Superseded in part (2026-10-02, ERP-COMPAT-02):** the "small Control Plane client resolving
> `legalEntityId` given `tenant_id`" idea below is withdrawn. A tenant can hold several legal entities
> (ADR-BCP-018); `legal_entity_id` arrives from the CP-issued provisioning/context and ERP only validates and
> persists it. See `docs/migration/erp-compat-01-semantic-delta.md` sections 6-7.

**Target**: `contracts/erp/v1/mapping.schema.json` --
`erp_`-prefixed `canonicalResourceId`/`erpResourceId` (opaque, pattern-constrained,
minted by the declared owner, never a leaked iDempiere id), `mappingId`
(`^map_[a-z0-9]+$`), `legalEntityId` (`^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$`, from
`contracts/legal-entity/registry.yaml`), a 5-value status enum
(`pending/active/suspended/retired/quarantined`), and temporal/revision fields
(`revision`, `effective_from`, `effective_to`, `replaces_mapping_id`).

**Current shape**: `db/migrations/0003_create_entity_mapping.sql`'s
`baobab.entity_mapping` has a bare-UUID `canonical_id` (no `erp_` prefix, no
`mapping_id` of its own), a 2-value status enum (`active`/`superseded`), no
`legal_entity_id` column at all, and no temporal/revision fields.
`modules/mapping/model.py` (`NativeRecordRef`, `MappingNotFoundError`),
`modules/mapping/resolver.py` (`CanonicalMappingStore` protocol,
`resolve_to_native`/`resolve_to_canonical`) and `modules/mapping/postgres_store.py`
would all need matching field additions. `tenant_id` columns
(`db/migrations/0002_create_tenant_mapping.sql`,
`db/migrations/0003_create_entity_mapping.sql`) also don't yet enforce the
`^tn_[a-z0-9]+$` pattern `contracts/control-plane/v1/domain.schema.json` defines.

**Blocked on**: where `legal_entity_id` values actually come from. There is no
Control Plane integration in this repo -- `contracts/legal-entity/registry.yaml`
is `nabhold/baobab-cp`'s registry, not baobab-erp's, and nothing here resolves
against it today. Bolting a `legal_entity_id` column onto `entity_mapping` with no
real source feeding it would be scaffolding with no data behind it. This phase
needs its own scoping pass on that question (most likely: a small Control Plane
client, analogous to `modules/integration/idempiere_client.py`, resolving
`legalEntityId` given `tenant_id`) before implementation starts.

**Done when**: `entity_mapping` and the mapping module match
`mapping.schema.json`'s field set, with `legal_entity_id` sourced from a real
(even if minimal) Control Plane resolution path, not hand-entered.

## Phase 3 -- HTTP boundary API

**Target**: `contracts/erp/v1/openapi.yaml` (`/provisioning-operations[/{id}]`,
`/mappings[/{mapping_id}]`, `/order-consequences/{commerce_order_id}`,
`/inventory-availability`), RFC 9457 `application/problem+json`
(`contracts/errors/v1/problem-details.schema.json`) for every error response, and
`Idempotency-Key` header handling on commands
(`contracts/idempotency/v1/policy.yaml`). Auth: `workloadOidc` (scopes `erp:read`,
`erp:provision`).

**Current shape**: `modules/application/server.py` is a stdlib
`http.server.BaseHTTPRequestHandler`, no framework, serving an entirely disjoint
surface (`/health/live`, `/health/ready`, `/context/resolve(-tenant)`,
`/mapping/resolve(-canonical)`, `POST /events/inbound`), each error returned as a
bespoke `{"error": "<message>"}` body, and no authentication at all --
`/context/resolve*`/`/mapping/resolve*` rely on network trust only (already an
open item under ADR-ERP-010).

**Blocked on**: ADR-ERP-005 has not yet chosen an HTTP framework (still `partial`,
stdlib-only by default), and ADR-ERP-010's auth gap is open. Both need their own
decision before this phase's endpoints can be built on solid ground rather than
adding a second ad hoc HTTP layer next to the first.

**Done when**: the four boundary paths above exist, return `problem+json` on
error, honor `Idempotency-Key`, and are protected by `workloadOidc` -- alongside
or replacing today's bespoke surface (a decision this phase should make
explicitly, not by accretion).

## Phase 4 -- Real payload production

Only after Phases 1-3 land: emit real `com.nabhold.erp.*` events whose `data`
conforms to `contracts/erp/v1/business-partner-projection.schema.json`,
`customer-projection.schema.json`, `warehouse-projection.schema.json`,
`invoice-outcome.schema.json`, `payment-outcome.schema.json`,
`inventory-availability.schema.json`, `order-consequence-status.schema.json`, and
`commerce-order-consequence.schema.json` -- using `money` (decimal-string amount +
ISO 4217 currency) and `quantity` (decimal-string value + unit) types throughout,
never floating-point JSON numbers for anything financial.

**Blocked on**: per `nabhold/shared` ADR-0005, adapter-private vendor mappings and
real payload production are explicitly gated on *consuming* repos (`baobab-trade`)
having compatibility tests against this public boundary first. That's an external
dependency baobab-erp cannot unblock alone -- track it, don't try to route around
it by shipping untested payloads into production ahead of a real consumer.

## Ownership reminder

`contracts/erp/v1/system-of-record.yaml` names ERP as the sole canonical owner for
exactly 7 of 24 tracked concepts: Business Partner, Supplier, Purchase Order,
Invoice, Warehouse, Accounting Entry, Asset. "No record is implicitly
bidirectional" -- every phase above should stay inside that ownership boundary
rather than assuming ERP owns a concept it doesn't.
