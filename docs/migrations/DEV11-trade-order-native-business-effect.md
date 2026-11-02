# DEV-11 — Single qualified Trade order -> native ERP consequence

**Status: IN PROGRESS / NOT ACCEPTED.** Owner: baobab-erp. Governing EA v2.3,
EA-DEV DEV-07/09/11, ADR-ERP-006/016/022, ADR-BCP-027 and Shared
ERP v1 commerce-order-consequence schema. Companions: Trade PR #188,
Infrastructure PR #72, CP PR #458, IAM PR #153.

## The three distinct stages

1. **Trade's durable fact:** An IAM-authenticated, CP-authorised native Trade
   commitment, with exactly one event outbox row in the *same native Medusa
   transaction* and the unchanged canonical envelope. The current
   `prepare-dev11-rabbit-event.ts` is deliberately **synthetic**; it is not
   authoritative evidence of buyer commitment or supplier legal authority.
2. **The real asynchronous chain:** RabbitMQ confirmed persistent publish
   and correct durable signed ERP event inbox receipt. Trade PR #188 uses
   separate PostgreSQL 17 instances and distinct real processes. Failures:
   broker rejection/unroute; native publisher death *after confirm, before
   PG settlement*; ERP consumer death *after durable inbox commit, before
   Rabbit ACK*; redelivery, forged signature, amended payload, DLQ and
   loss of lease. The connected job remains unqualified until successful
   current-head CI evidence has been retrieved and independently checked.
3. **Native iDempiere business consequence:** The ERP inbox worker must
   receive a separately provisioned, exact event-scoped, CP-owned RUNTIME
   PlatformContext, current mandate, exact legal actor, market, capability,
   provider readiness and current documentary negative-scope decision.
   It must execute through the **real iDempiere** financial/rest veto,
   persist exactly one C_Order and its lines, produce ERP consequence,
   ERP's own registered outcome event and mark the inbox processed.
   An accepted inbox record is NOT a native order.

## Operator-owned development authority (explicit, no tenant defaults)

The ERP worker's `BAOBAB_ERP_INBOX_AUTHORITY_REGISTRY_FILE` points to a
**private, absolute, regular file** (0600 permissions; no symbolic link or
group/world write). It is permitted only in development/test/integration;
it NEVER enables staging or production. No registry is accepted from a
CloudEvent. For one event its schema is:

```json
{
  "schema": "baobab.erp.dev11.operator-authority.v1",
  "entries": [
    {
      "event_id": "1d032305-669c-45df-b988-01166de4c14c",
      "source": "urn:baobab-platform:service:baobab-trade",
      "tenant_id": "tn_dev11synthetic",
      "idempotency_key": "dev11-rabbit-connected:1d032305-669c-45df-b988-01166de4c14c",
      "commerce_order_id": "order_dev11_fixture",
      "legal_entity_id": "LE-DEV11-SYNTHETIC",
      "context_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
      "operating_organisation_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
      "market": "ZA",
      "activity": "B2B_TRADE_ORDER",
      "capability": "accounting.order.create",
      "authority_reference": "synthetic:dev11/operator-policy-example",
      "engine_instance_id": "ei_dev11synthetic",
      "ad_client_id": 11,
      "ad_org_id": 11,
      "finance_baseline_version": 1
    }
  ]
}
```

**EXAMPLE ONLY.** These IDs/permission strings are not approved
capabilities, do not represent a real CP-issued context, and are NEVER
accepted as authority without a fresh, authenticated **real** CP response,
current native placement, Finance baseline, operating organisation,
source registry capability binding and independent native provider check.
For a real run, obtain the exact role/activity/capability and source reference
from accepted provider/Shared decisions. Do not invent or copy these values.
The protected command denies any missing or mismatched element.
For an actual native-engine acceptance, the **iDempiere JVM** must separately
run with `-Dbaobab.erp.native.environment=acceptance` and its
`native-finance-veto-active` sentinel must be independently read back; the
Python worker's `BAOBAB_ENVIRONMENT=integration` alone does **not** activate
the JVM veto, whose explicit integration mode is unprotected for isolated
fixtures. A missing JVM sentinel blocks L4 acceptance even if a matching
database C_Order and attribution row are present.

When the operator securely provisions the exact immutable source binding,
the worker requires:

- `BAOBAB_ENVIRONMENT=integration` (or development/test),
  `BAOBAB_REQUIRE_LEGAL_ACTOR_GATE=true`,
  `BAOBAB_ERP_INBOX_PROFILE=dev11-order-placed`
- `BAOBAB_ERP_INBOX_AUTHORITY_REGISTRY_FILE` (private verified source)
- `BAOBAB_ERP_CP_URL` (private CP HTTPS),
  `BAOBAB_ERP_CP_OAUTH_TOKEN_URL` (IAM HTTPS),
  `BAOBAB_ERP_CP_WORKLOAD_CLIENT_ID`,
  `BAOBAB_ERP_CP_WORKLOAD_SECRET_FILE` (private file)
- `DATABASE_URL` direct ERP PostgreSQL connection and
  `IDEMPIERE_CLIENT_CREDENTIALS_JSON` for exact native AD_Client/AD_Org

Absent operator binding => `LEGAL_ACTOR_PENDING`, not permission.
CP denies/unavailable, documentary hold, withdrawn baseline, wrong
placement/client/org, missing mapper, engine error or revoked mandate must
produce named blocked/retry/dead-letter states **without** an unauthorised
native C_Order. All real CP double checks and iDempiere JVM veto remain
required; this development integration is not provider certification.

## Read-only independent native-effect verifier

After real iDempiere 13 is running, native database migrations and
approved synthetic placement are installed, and the actual authorised
inbox worker has processed a *non-faked* Trade event, run as an independent
read-only database observer:

```sh
ERP_DATABASE_URL="postgresql://<read-only-user>@<real-native-pg17>/idempiere" \
  python3 -B scripts/dev11_verify_native_idempiere_order.py \
    --tenant "$EXACT_TENANT" \
    --event-id "$EXACT_TRADE_EVENT_UUID" \
    --legal-entity "$EXACT_LEGAL_ENTITY" \
    --ad-client "$EXPECTED_AD_CLIENT" \
    --ad-org "$EXPECTED_AD_ORG" \
    --output "$PRIVATE_EVIDENCE_DIR/native-order.json"
```

Expected checks: event processed once; native `C_Order` by exact
`POReference` exists **exactly once across companies**, with same native
client/org and real `C_OrderLine`; `baobab.order_execution` joins
original event and native ID, `baobab.order_consequence` is present,
registered ERP consequence event exists once, and native placement is
in force. The checker also requires iDempiere JVM-written
`baobab_native.finance_authority_attribution` for the same native C_Order,
linked to its native source document and CP decision/mandate; a bare row
inserted outside the JVM is insufficient. The checker never reports customer invoice posting or
`Fact_Acct` merely because an order draft exists.

The real protected iDempiere 13 / PostgreSQL17 / CP / Hydra / Kratos
acceptance topology already exists at
`idempiere/acceptance/erp-a/compose.yaml`. Reuse its exact source,
TLS, native-veto and company-isolation safeguards. Its existing driver
and its real native posting evidence **do not yet contain** the
connected RabbitMQ/Trade order-to-ERP scenario. A separate scenario
must be added and actually executed against that running engine,
including unknown-outcome adoption and revocation/replay, before
native C_Order qualification can turn PASS.

## Independent full L4 evidence join

A consumer-produced or Trade-produced `"passed":true` is never
acceptance. The separate Infrastructure #72 verifier must read
immutable GitHub current-head source pins and workflow/job/step
conclusions, independently exported Jaeger traces from real source,
publisher and ERP consumer, broker confirmations/ACK/DLQ outcomes,
ERP's real native database read-only receipt, negative tests and
teardown. Join that to the three estate-owned Playwright/axe/visual/
Lighthouse/current static budget receipts.

## Engine-local real execution implementation (added 2026-11-02)

The existing protected ERP-A acceptance runner, not an invented REST server,
now supports the explicit flag `DEV11_REAL_NATIVE_ACCEPTANCE=true`. The
new owner workflow is
`.github/workflows/dev11-real-native-engine.yml`; it checks out exact
CP and IAM source SHAs, builds the real iDempiere 13 image and real
test-only OSGi driver, provisions actual Hydra client credentials and
CP context/mandate, and uses RabbitMQ to deliver a signed synthetic Trade
order into ERP's canonical PostgreSQL inbox. ERP's separate worker then
performs fresh CP legal-actor/documentary checks and calls into the
**real iDempiere JVM**. This is an opt-in test-only file transport because
the separate REST OSGi plugin is not installed in the pinned engine image.

`modules/integration/idempiere_gate_d_real.py` is guarded to
`integration`, `BAOBAB_ERP_INBOX_PROFILE=dev11-order-placed`,
`BAOBAB_REQUIRE_LEGAL_ACTOR_GATE=true`, a verified test-only JVM root,
and GardenWorld's exact company/org 11. All other companies, runtime
environments, generic native tables, arbitrary SQL and additional order
lines are refused. Native `C_Order` and `C_OrderLine` are read back
directly from PostgreSQL, and an uncertain response can only be adopted
if every native fact matches the same canonical order. It is **not a
production business API**.

The two standalone, independent observers are:

- `scripts/dev11_verify_native_idempiere_order.py` reads native
  `adempiere.c_order` and `c_orderline`, ERP's canonical inbox,
  `order_execution`, consequence, outbox and immutable JVM CP attribution.
- `scripts/dev11_verify_cp_native_lineage.py` opens separate *read-only*
  CP and native PostgreSQL transactions and joins every native CP decision
  to CP's own immutable `registry.erp_posting_authority_decision` row,
  RUNTIME context and independently reviewed legal-actor mandate.

The connected runner also sends an unchanged broker redelivery and
revokes the real CP sales mandate before a second order; it requires
zero second native orders. Its output stays explicitly
`full_medusa_buyer_commitment_proven=false`,
`independent_exported_trace_graph_proven=false`,
`l4_ops_01=BLOCKED`. Even a successful real engine-local workflow
**does not certify the complete Trade vertical**. Infrastructure #72
must independently fetch and verify it as an eighth source-pinned owner
before any source convergence can be considered.

**Current status:** connected source changes committed; workflow execution
and independent GitHub artifact verification still pending. A queued
GitHub Actions run, a mocked unit test or a hand-authored report is not
provider/runtime acceptance. Do not merge or activate protected
staging/production gates.

**Until each distinct observation is present and independently
verified, `l4_ops_01=BLOCKED`. Never merge for this milestone based
on unit-mock positives, synthetic native results or a passing inbox
admission alone.**
