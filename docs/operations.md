# Deployment

`compose.yaml` provides the runtime baseline (Phase 4): a `postgres` service, an
`idempiere` service built from `idempiere/Dockerfile` (pins the upstream image, stages
in the Baobab OSGi extension bundles), a one-shot `baobab-db-migrate` service that
applies `db/migrations/` before anything else starts, a `baobab-app` service built from
`modules/Dockerfile` exposing the HTTP application layer
(`modules/application/server.py`: `/health/live`, `/health/ready`,
`POST /events/inbound`), and a `baobab-dispatch-worker` service (same image) that
periodically invokes `modules/application/dispatch_worker.py` to drain the event
outbox, and a `baobab-inbox-worker` service that periodically invokes `modules/application/inbox_worker.py` to execute received
`trade.order.placed` events (see `docs/events.md`, "Executing `trade.order.placed`"), and a `baobab-provisioning-worker` service that
periodically invokes `modules/application/provisioning_worker.py` to provision accepted legal-entity commands.

`modules/application/dispatch_worker.py` (outbox delivery) runs to completion and exits
by design -- it is not itself a long-lived daemon. The `baobab-dispatch-worker` Compose
service supplies the periodic invocation (`modules/scripts/dispatch_worker_loop.sh`, a
plain sleep loop configurable via `BAOBAB_DISPATCH_INTERVAL_SECONDS`, default 60s): the
loop is deployment configuration, not application code, and a failed tick is logged and
retried on the next tick rather than crashing the loop. A non-Compose deployment can
instead point cron or a systemd timer directly at `python -m application.dispatch_worker`
on the same schedule.

### Event destinations (dispatch worker)

Configure one or both; at least one is required. The Control Plane group is all-or-nothing. The legacy webhook is enabled by `BAOBAB_WEBHOOK_URL` and then needs `BAOBAB_EVENT_SIGNING_SECRET`; the secret alone does not enable it, because the application also uses it for inbound events.

| Destination | Carries | Settings |
|---|---|---|
| Control Plane event ingress (signed delivery) | `provisioning.changed` | `BAOBAB_CP_EVENT_INGRESS_URL` (https), `BAOBAB_CP_EVENT_KEY_ID`, `BAOBAB_CP_EVENT_SECRET_B64` (standard base64, at least 32 bytes) |
| Legacy webhook | every other canonical event | `BAOBAB_WEBHOOK_URL`, `BAOBAB_EVENT_SIGNING_SECRET` |

A type whose destination is not configured waits in the outbox (pending, not failing) until it is. Each run prints one JSON line per
destination (`event: outbox.dispatch`) with what this pass did (`delivered`, `retried`, `dead_lettered`) and the backlog after it (`pending`, `retry`,
`dead_letter`, `delivered_total` (every event ever delivered to the destination, not this pass's count), `due`, `oldest_undelivered_seconds`): alert on any `dead_letter` and on a growing
`oldest_undelivered_seconds`. The delivery key is provisioned by an operator, never committed; rotate it by adding the new key to the
Control Plane first, switching `BAOBAB_CP_EVENT_KEY_ID`/`BAOBAB_CP_EVENT_SECRET_B64`, then retiring the old key after the Control
Plane's replay window (300 seconds) and the longest retry horizon (72 hours) have passed.

### Inbox worker

Same one-shot pattern as the dispatch worker (`modules/scripts/inbox_worker_loop.sh`, `BAOBAB_INBOX_INTERVAL_SECONDS`, default 15s), and any number
may run at once. It needs `DATABASE_URL` (a direct connection) and `IDEMPIERE_CLIENT_CREDENTIALS_JSON` (the same per-AD_Client JSON the
application reads; a tenant without an entry is blocked, not failed). `BAOBAB_INBOX_BATCH_LIMIT` (default 50) bounds a pass and
`BAOBAB_INBOX_LEASE_SECONDS` (default 300, minimum 30) is the claim lease: keep it above the longest time one order can spend in the engine, because an
expired lease lets another worker take the row. Each run prints one JSON line (`event: inbox.execute`) with this pass's outcomes by status and
code and the backlog by status afterwards: alert on any `dead_letter`, on `blocked` rows older than an hour, and on a growing `received` count.
Deploying it also executes any `trade.order.placed` rows already `received` before it existed.

### Provisioning worker

`POST /provisioning-operations` accepts a command and answers 202; `baobab-provisioning-worker` then provisions each legal entity
(`modules/scripts/provisioning_worker_loop.sh`, `BAOBAB_PROVISIONING_INTERVAL_SECONDS`, default 30s; `BAOBAB_PROVISIONING_BATCH_LIMIT`,
default 10). Same one-shot pattern as the other workers, and any number may run: an operation is claimed with a session advisory lock, so
`DATABASE_URL` must be a direct connection. A worker that dies releases its lock with its connection and the next one resumes from the recorded
steps; nothing is created twice (native ids are recorded per step, and an engine record created just before a crash is adopted by the marker
the step wrote into its `Description`).

It needs, per EngineInstance, a provisioner identity in `IDEMPIERE_PROVISIONER_CREDENTIALS_JSON` (`{"<engine_instance_id>": {base_url, username,
password, client_id, role_id, organization_id}}`). It is deliberately not the per-AD_Client integration credential: that AD_Client does not exist
until provisioning runs, and ADR-ERP-019 forbids a shared superuser, so grant it only what client provisioning needs. Accounting and localisation
run iDempiere processes whose ids differ per installation: set both `IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING` and
`IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON` (`{"<country>": <id>}`) or neither. They are checked before the first step, so an operation
never creates an AD_Client it cannot then configure.

Outcomes are fixed codes (`baobab.erp_provisioning_operation.outcome_code`): `READY`; `ENGINE_UNAVAILABLE` and `NOT_READY` (retried with backoff,
30 s doubling to 1 h, 24 attempts); `ENGINE_UNCONFIGURED`, `PROCESS_UNCONFIGURED`, `ENGINE_AUTH` (blocked: an operator can fix it; retried every
15 minutes for 72 hours); and failures (`ENGINE_REJECTED`, `STATE_DRIFT`, `STATE_UNREADABLE`, `STEP_INVALID`, `DUPLICATE_NATIVE_RECORDS`,
`TENANT_MAPPING_CONFLICT`, `ATTEMPTS_EXHAUSTED`, `BLOCKED_HORIZON_EXCEEDED`), after which the command reports `failed` with `ERP_PROVISIONING_FAILED`
and the worker leaves it for an operator. Each run prints one JSON line (`event: provisioning.execute`): alert on `failed`, on `blocked` older than
an hour, and on `planned` operations that are not draining.

Not covered yet: the new AD_Client's own integration credentials (`IDEMPIERE_CLIENT_CREDENTIALS_JSON`, which order execution reads) are still set by
hand after provisioning, and none of this has run against a live iDempiere.

## Production requirements

1. Build images from a reviewed commit and immutable upstream pins
   (`upstream.lock.yaml`).
2. Replace every placeholder secret; store secrets outside Git.
3. Terminate TLS before iDempiere or `baobab-app`, or in front of an approved reverse
   proxy; iDempiere itself requires HTTPS from version 9 onward.
4. Restrict PostgreSQL to the private application network.
5. Back up the database (`adempiere` and `baobab` schemas together) and test restore
   before promoting a release.
6. Apply `db/migrations/` as a controlled pre-deployment step (`baobab-db-migrate` in
   Compose, or `db/migrate.sh` directly).
7. `modules/application/dispatch_worker.py` runs periodically via the
   `baobab-dispatch-worker` Compose service by default; a non-Compose deployment must
   schedule it itself (every minute or so) so outbox events actually get delivered.
8. Monitor HTTP health (`/health/ready`), outbox backlog and dead-letter count, database
   capacity, disk capacity, and certificate expiry.

Compose is the supported initial single-host deployment. Scaling to an orchestrator
requires an ADR backed by measured availability, capacity, or operational requirements
(ADR-ERP-013); production orchestration is owned by `nabhold/infrastructure`.

## Status

No production `EngineInstance` exists yet. `baobab-app`'s HTTP surface is currently
just health checks and the inbound event webhook -- see `architecture/conformance.yaml`
for what's still planned (a real iDempiere-facing client, LegalEntity accounting
configuration, and more).
