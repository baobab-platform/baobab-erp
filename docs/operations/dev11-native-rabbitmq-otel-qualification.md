# DEV-11 — ERP native RabbitMQ inbox admission and OTel boundary

**Status:** Draft engineering candidate, **not** L4-OPS-01 acceptance or a protected deployment.
Owners: ERP application/inbox, iDempiere native authority, Infrastructure RabbitMQ topology.
Dependencies: accepted EA v2.3 / DEV-11; ADR-ERP-006/016; ADR-Infra-0012/0016.

## Production-safe admission boundary

`modules/application/amqp_consumer.py` runs as an independent ERP process.
It does not create exchanges or queues. It connects to the exclusively
pre-provisioned durable `baobab.erp.trade-order.v1` quorum queue,
checks message size/content type and HMAC signature, parses the closed Shared
CloudEvent envelope, and applies the existing registry/producer/dataschema
rules. Admission uses the genuine `PostgresInboxStore` with uniqueness on
`(ce_source,event_id)` and an immutable semantic replay check. Differences in
`traceparent` or `tracestate` cannot create an extra business event; changed
business attributes cannot overwrite the original admission. Producer
`traceparent` is used for diagnostics only **after** signature verification.

The AMQP consumer sends **manual ACK after durable PG commit**; invalid
signatures/contracts reject to a governed DLX; unknown PG outcomes NACK and
requeue. Broker publisher-confirmations are **not** consumer business effects.
This process never calls iDempiere.

## Running the disposable consumer

Requires explicit `BAOBAB_ENVIRONMENT=development`, a disposable Postgres 17
with all `baobab-erp/db/migrations/` applied, `DATABASE_URL`,
`BAOBAB_RABBITMQ_URL`, and a runtime-injected
`BAOBAB_EVENT_SIGNING_SECRET` (minimum 24 chars). The queue name
`BAOBAB_AMQP_INBOX_QUEUE` must remain `baobab.erp.trade-order.v1`.
The Trade and ERP processes use the *same* run-owned test signing key,
held privately by the runner. In staging/production AMQPS is mandatory, and
per-producer workload keys and topology approvals are a separate security gate.

With `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://otel-collector:4318/v1/traces`
in the development-only environment, the official Python OpenTelemetry SDK
exports consumer spans with causal links to the **signed** event context.
No raw canonical event bodies, credentials, SQL, business names, customer
details or unbounded exception strings are exported. Graceful SIGTERM stops
consumption and flushes batches.

## Genuine crash / replay qualification

Trade #188's disposable `dev11-rabbit-connected.yml` owns a **separate
operating-system ERP consumer process** and an additional development-only
crash-injection worker. The injected hook executes **only after the real
PostgreSQL inbox write commits and before a RabbitMQ ACK**; the harness
terminates that process and starts a fresh unmodified ERP consumer. An
independent broker-management probe must observe manual ACK after recovery,
and ERP PG must hold exactly one receipt despite real redelivery.

The hooked callback defaults to `None` in the shipped ERP process; no crash
behavior is enabled by production runtime inputs. Unit tests retain signed
admission, broker ACK and NACK ordering, changed-type/signature rejections,
dedup, TLS prohibition on plaintext protected traffic, and the no-ACK crash
boundary. **Passing unit tests are source coverage, not connected evidence.**

## Native iDempiere effect — not yet qualified

The separate `modules/application/inbox_worker.py` claims rows with
`FOR UPDATE SKIP LOCKED`, keeps the signed original W3C context, and
instruments actual native outcomes. Existing O2C execution uses current
customer/product/tenant mappings, native `POReference` reconciliation,
`baobab.order_execution`, transactional consequence/outbox and **lease
fencing**. However, that path has not yet been linked to this real Rabbit
profile with a running iDempiere 13 and issuer/CP current-authority decision.
The worker's protection must be enabled and its
`authority_for(claim)` implementation independently verified before any
positive native posting test; missing current CP authority, legal actor,
documentary clearance or mandate MUST BLOCK, not fall back to the event's
tenant. No protected staging/production effect may be inferred.

The next independently necessary qualified proof is a real authorised
`trade.order.placed` payload, actual iDempiere POST and read-back, a
post-engine/pre-ERP-commit crash, adoption by `POReference` rather than
recreation, second-company isolation, and a single ERP consequence/outbox
event. Until then: **L4-OPS-01 = BLOCKED**.
