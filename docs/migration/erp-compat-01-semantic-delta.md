# ERP-COMPAT-01 — Semantic delta census (Shared `2da1a42` → `739f0ca`)

Status: census only. **No re-pin, no behaviour change.** `contracts.lock.yaml`
stays at `2da1a42` until ERP-COMPAT-02…06 pass (ERP-COMPAT-07 moves it).
Date: 2026-10-02. Method: `git diff 2da1a42 739f0ca -- <contract>` in
`baobab-platform/shared` for each of the 19 contracts in the lock (500 Shared
commits in between), plus the contracts and registries added since that ERP
does not yet list.

## 1. The 19 locked contracts

| Contract | Delta | Class |
|---|---|---|
| `erp/v1/mapping.schema.json` | `$id` host only | unchanged |
| `erp/v1/domain.schema.json` | `$id` host only | unchanged |
| `erp/v1/{business-partner,customer}-projection`, `commerce-order-consequence`, `inventory-availability`, `invoice-outcome`, `order-consequence-status`, `payment-outcome`, `provisioning-request`, `provisioning-state`, `warehouse-projection` `.schema.json` (11) | `$id` host only | unchanged |
| `errors/v1/problem-details.schema.json` | `$id` host only | unchanged |
| `idempotency/v1/policy.yaml` | policy `name` only (`nabhold-` → `baobab-platform-idempotency-policy`) | unchanged (rename) |
| `events/v1/envelope.schema.json` | `type` pattern `^com\.nabhold\.…` → `^com\.baobab-platform\.…`; description | **breaking** (type namespace) |
| `erp/v1/asyncapi.yaml` | all 9 event `name`s `com.nabhold.…` → `com.baobab-platform.…`; channel addresses `nabhold.erp.{commands,outcomes}.v1` → `baobab-platform.erp.…` | **breaking** (names/addresses) |
| `erp/v1/openapi.yaml` | server/OIDC hosts renamed; `/inventory-availability` now documented against new `inventory-availability-query.schema.json`; SKU/warehouse id descriptions | additive (docs) + one new referenced schema |
| `erp/v1/system-of-record.yaml` | schema 1.0 → **1.1** (ADR-BCP-018): Legal Entity runtime owner `shared` → `control-plane` (Shared keeps contract authority); Organisation owner `unassigned` → `control-plane`; sync direction `shared_to_consumers` → `control-plane_to_consumers` | **behavioural** |
| `control-plane/v1/domain.schema.json` | `legalEntityId` description (CP-known, external ids CP-authoritative); +14 new id types (`engineId`, `engineInstanceId`, `engineReleaseId`, `deploymentObservationId`, `tenantProvisioningId`, `tenantProvisioningState`, `provisioningPlanId`, `changesetId`, `providerMigrationId`, `approvalDecisionId`, `operationId`, …) | additive; one semantic note |

Result: 16 of 19 are cosmetic (host/name). **Three are breaking**
(`envelope.schema.json`, `asyncapi.yaml`, plus the `com.nabhold` → `com.baobab-platform`
type namespace they define) and **one is behavioural**
(`system-of-record.yaml`, Legal Entity authority moves to Control Plane).
No field of any projection/outcome/mapping/provisioning payload schema changed.

## 2. Added since the pin and not in ERP's lock

| Contract | Why ERP needs it |
|---|---|
| `erp/v1/inventory-availability-query.schema.json` | request contract for `GET /inventory-availability` (openapi now references it) |
| `erp/v1/capabilities.yaml` | canonical capability definitions ERP owns (`finance.order-consequence.process`, …); provider side is ERP's `.baobab/capability-provider.yaml` |
| `events/v1/event-registry.yaml` (+schema) | every `com.baobab-platform.erp.*.v1` type is registered with `producer: baobab-erp`; ERP may emit only registered types, and no second vocabulary |
| `events/v1/context-registry.yaml` (+schema) | `erp` is the one non-tenant-scoped context exception (stewards `[baobab-erp]`) |
| `events/v1/compatibility/legacy-trade-erp-event.json` | archived shape of ERP's current envelope |
| `erp/v1/examples/*.json` (9) | golden payloads for conformance tests |
| `organisation/v1/*` (ADR-BCP-018) | Organisation / Legal-Entity authority split referenced from `system-of-record.yaml` |

These are lock additions for ERP-COMPAT-07, each justified by a conformance test.

## 3. ERP state against the target (what each COMPAT step must close)

| Area | ERP today (`main` = #42) | Target | Step |
|---|---|---|---|
| Identity / mapping | `baobab.entity_mapping` has since 0008: `legal_entity_id`, `revision`, `effective_from/to`, `replaces_mapping_id` (BIGINT FK). Still missing: `mapping_id` (`^map_[a-z0-9]+$`), `erp_`-prefixed `canonical_reference`/`erp_resource_id` (today bare `canonical_id` UUID + native integer id), 5-value status (today `active`/`superseded`), `tn_` tenant pattern on `tenant_id`. The lock comment calling this "not yet reconciled" is therefore only partly stale. Legal-entity source must now be **Control Plane** (system-of-record 1.1), not a Shared registry. | `mapping.schema.json` | 02 |
| HTTP boundary | `modules/application/server.py` serves `/context/*`, `/mapping/*`, `/outbox/record`, `/sales-orders*`, `/shipments*`, `/customer-invoices*`, `/payments*`, `/events/inbound`. **None** of the 6 openapi paths exist: `/provisioning-operations[/{id}]`, `/mappings[/{id}]`, `/order-consequences/{commerce_order_id}`, `/inventory-availability` | openapi paths, scopes, idempotency | 03 |
| Errors | ad-hoc `{error: …}` JSON | RFC 9457 `application/problem+json` on every error, negative-case tests | 04 |
| Events | 9-field legacy envelope (`event_id, event_type, schema_version, occurred_at, source, correlation_id, tenant_id, entity_id, payload`); `event_type` values like `erp.payment.completed.v1`, `trade.order.accepted`; `contracts/events/envelope.schema.json` self-declared; `causation_id` declared but unused | CloudEvents 1.0 profile, `com.baobab-platform.erp.*.v1` registered types, `(source, id)` dedup | 05 |
| Conformance proof | tests validate against ERP's own schemas | tests read the exact Shared commit in the lock and refuse any other | 06 |

## 4. Corrections to carry forward

1. The reconciliation plan and lock comments still say `com.nabhold…` /
   `nabhold/shared`; every new type must use `com.baobab-platform…`.
   ERP code contains no `com.nabhold` event types today (only docs/ADR/tests
   text), so the rename is a contract/documentation concern, not a data
   migration. Historical migrations stay immutable.
2. Legal Entity authority is Control Plane at runtime (ADR-BCP-018). ERP-COMPAT-02
   must resolve `legal_entity_id` through the CP context path already used by
   `modules/context`, never a Shared-registry lookup, and must not use names.
3. Trade is now on the converged contracts (T-COMPAT-01…07), so the earlier
   "no live consumer" framing in `docs/reconciliation-plan.md` is out of date:
   ERP is the remaining blocker for EA-01.
4. iDempiere remains ERP authority behind the anti-corruption boundary
   (ADR-ERP-004); nothing in COMPAT-02…07 changes iDempiere internals.

## 5. Reproduce

```
git -C shared diff 2da1a429 739f0ca -- <each path in contracts.lock.yaml>
```

## 6. Owner decisions (2026-10-02)

* **iDempiere CVE-2026-89425 (nested jackson-core 2.15.2 in the Hazelcast bundle):** wait for or pin an
  upstream image that already ships the fix; no further jar surgery. On 2026-10-02 the only release tag
  (`13-release`) is the current pin (2026-04-07); `13-daily` (2026-10-01) is a nightly, not a release,
  and is not pinned without explicit approval and a scan. ERP merges stay gated on `foundation / container`.
* **Legal-entity source (ERP-COMPAT-02):** Control Plane is the authority; ERP adds **no**
  `tenant_id -> legal_entity_id` lookup (a tenant may have several legal entities via explicit
  TenantLegalEntityMapping, ADR-BCP-018) and does not use the administrative `GET /tenants/{id}`.

## 7. ERP-COMPAT-02 implementation (migration 0012)

| Source of `legal_entity_id` | Rule |
|---|---|
| ERP provisioning | `legal_entity_ids[]` of the canonical provisioning request |
| Mapping created in provisioning | the specific legal entity being provisioned |
| Runtime request | the legal entity of the trusted resolved context |
| Event / projection | explicit canonical `legal_entity_id` where the contract requires it |
| Historical rows | separate reconciliation against Control Plane; never defaulted from the tenant |
| Manual input, Shared registry (reference only), ERP DB inference, names | never authoritative |

* `baobab.entity_mapping` gains `mapping_id` (`map_…`), `erp_resource_id` (`erp_…`, boundary-minted, never an
  iDempiere id), `canonical_owner` (with `canonical_type`/`canonical_id` = `canonical_reference`) and
  `quarantine_reason`; status widens to `pending|active|suspended|retired|quarantined` (`superseded` -> `retired`).
* Legacy `active` rows with no legal entity become `quarantined` (verified on a pre-0012 database: active/no
  legal entity -> quarantined, superseded -> retired, active with legal entity unchanged). Quarantined rows never
  resolve (`find_native`/`find_canonical` serve `active` only). A live mapping without a legal entity is refused
  by a CHECK.
* `tn_…` tenant and canonical legal-entity grammars are enforced for every new or changed row (`NOT VALID`
  constraint; legacy rows are reported, not rewritten) and in `mapping.identifiers`.
* `mapping.context.ControlPlaneContextPort.validate_context(tenant_id, legal_entity_id)` is the seam: it
  validates an explicit pair and has no lookup-by-tenant method. A real workload-facing implementation needs a
  narrow CP relation contract (not the admin API, not the CP database) and is out of scope here.
* `Mapping.to_contract()` renders the public mapping without vendor bindings and refuses to publish an
  unreconciled one.

Remaining for later steps: the `/mappings` HTTP surface and `replaces_mapping_id` as a `map_` id on the wire
(03), exact-pin schema validation of `to_contract()` output (06), and the CP backfill process for quarantined rows.

## 8. ERP-COMPAT-03a — Boundary API read surface

Implemented against `contracts/erp/v1/openapi.yaml` (Shared 739f0ca): `GET /mappings/{mapping_id}` and
`GET /mappings`, behind authentication (401) -> header validation (400) -> scope (403) -> tenant claim (403),
with the tenant taken only from the token's `tenant_id` claim, public mapping documents with no vendor binding,
RFC 9457 problem documents (`application/problem+json`, correlation id echoed, `trace_id` from `traceparent`).
Response and problem bodies were validated against the Shared 739f0ca schemas in a one-off check; the permanent
exact-pin proof is ERP-COMPAT-06.

Declared but not implemented (501 problem+json, never fabricated) and what each waits on:

| Operation | Waiting on |
|---|---|
| `POST /provisioning-operations` | a Control Plane assignment source and governed finance baseline (the contract request is thin; ERP's internal request is not), boundary-minted `op_` operation id |
| `GET /provisioning-operations/{id}` | the `op_` operation id and tenant column on `erp_provisioning_operation`, state mapping |
| `GET /order-consequences/{commerce_order_id}` | a consequence read model over the order-to-cash flow |
| `GET /inventory-availability` | an iDempiere stock query and warehouse id mapping |

External dependency: Baobab IAM grants ERP workloads only `erp:integrate`. `erp:read` / `erp:provision` and a
`tenant_id` claim on ERP-bound tokens must be granted by the owner before these routes serve traffic; they fail
closed until then. No scope was added to IAM here.

## 9. CVE-2026-89425 — alternative solution (ADR-ERP-004 section 5 mitigation)

Evidence (CI probe, `scripts/probe-idempiere-image.sh`, run on `13-release` and `13-daily`):
the vulnerable jackson-core 2.15.2 is Hazelcast 5.3.7's own shaded copy
(`com/hazelcast/shaded/com/fasterxml/jackson`) inside `lib/hazelcast.jar` of
`org.idempiere.hazelcast.service`. Neither `13-release` (2026-04-07) nor the `13-daily` build of
2026-10-01 fixes it, so waiting for an upstream image does not resolve it today.

The bundle only provides iDempiere's optional cluster service: `bundles.info` lists it at start
level 4 with autostart `false`, no plugin in the image requires or imports from it, and ERP runs one
iDempiere node per EngineInstance (ADR-ERP-003). `idempiere/Dockerfile` therefore removes the unused
component (no jar is modified, no scan exception is added) behind a guard that fails the build if
the bundle set changes or any plugin starts to depend on it. The obsolete `.trivyignore` entry for
that jar is dropped. The guard was exercised against a synthetic plugin tree (removal succeeds;
a dependent plugin or a missing bundle fails). **Not verified here:** a full iDempiere boot without
the bundle, because no CI job or environment boots the image; the owner should confirm before this
reaches an environment that runs one.

## 10. ERP-COMPAT-04 — Problem Details on every route

All error responses are `application/problem+json` (`type`, `title`, `status`, `code`, `correlation_id`,
`retryable`, optional `detail`/`trace_id`). Codes: `ERP_INVALID_REQUEST` 400, `ERP_AUTHENTICATION_REQUIRED` 401,
`ERP_FORBIDDEN` 403, `ERP_RESOURCE_NOT_FOUND` 404, `ERP_OPERATION_NOT_IMPLEMENTED` 501,
`ERP_UPSTREAM_REJECTED` 502 (iDempiere rejected the request), `ERP_SERVICE_UNAVAILABLE` 503 (retryable),
`ERP_INTERNAL_ERROR` 500 (retryable; details logged, not returned). Behaviour changes callers can see:
missing `/context/resolve` parameters are 400 instead of 404; 401/503/500 bodies no longer carry validator or
driver text; the `error` member is gone (the Java client was updated to read `detail`). Negative-case proofs:
`tests/integration/test_legacy_problem_details.py`.

## 11. ERP-COMPAT-05 — CloudEvents envelope

* `modules/events/cloudevent.py` (envelope), `modules/events/registry.py` (the 8 types ERP produces — the
  seven `erp.*` types plus `customer.buyer-commercial-profile.changed.v1`, which the buyer-organisation
  contract registers to baobab-erp and which the census had missed — and the 2 Trade types it consumes).
* Migration 0013: canonical members stored on outbox/inbox; inbox dedup is `(source, id)`; legacy rows kept,
  undelivered legacy outbox rows parked as `held` (verified on a pre-0013 database: pending/retry -> held,
  delivered/dead_letter and the legacy inbox row untouched).
* Delivery is structured mode (`application/cloudevents+json`); inbound accepts only registered Trade events
  with their registered `dataschema` and producer; the legacy body is a 400 problem.
* Proof against Shared 739f0ca: all 9 `erp/v1` examples parse and round-trip, and the registry index equals
  Shared's registry (`tests/contract/test_shared_event_examples.py`, run with `SHARED_CONTRACTS_DIR`).
* Honest limit: ERP's domain recorders still produce legacy-shaped events with iDempiere native ids and no
  registered canonical counterpart, so they are `held`, not delivered. Producing the registered `erp.*` events
  needs an outcome projection (order_version, revisions, totals, erp_ ids) and the consequence read model; until
  then ERP delivers no events.
