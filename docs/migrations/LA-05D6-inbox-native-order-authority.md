# LA-05D6 — Protect Trade inbox -> native ERP order creation

**Authority:** Accepted ADR-BCP-026 and ADR-BCP-027 / closure Package 4, extending ERP's merged LA-05D4 and D5 guards.

## Boundary closed

The durable `trade.order.placed` inbox executor previously called `IdempiereOrders.create_record("C_Order",...)` directly via `_find_or_create`, **outside** the protected `order_to_cash.service.create_sales_order` path. A production OrderToCash service wrapper alone could not defend that bypass.

This change:

1. `_find_or_create` rejects *even a direct caller* in protected environments without the exact private, operation-scoped ERP native-action marker. The guard executes **before** the native lookup or creation, including an attempt to adopt an existing order.
2. In staging/production/unknown environment, the inbox must have an independent `InboxNativeAuthority` for the exact claimed order. The trusted composition root injects a reviewed `NativeActionPolicy`, a CP-issued context-bound `LegalActorOperation`, authenticated current legal-actor assessor, independent documentary remediation checker and native ERP readiness checker. Missing authority yields `LEGAL_ACTOR_PENDING`, no engine order.
3. The existing `perform_governed_native_action` checks matching order reference, tenant, expected actor, role, activity, market and exact declared capability and source policy; probes documentary holds twice, ERP readiness, CP final revocation, then creates a temporary private execution marker **only** around the native lookup/adoption/create.
4. `application.inbox_worker.run_once` now accepts an **operator-owned `authority_for(claim)`** injection. It is never populated by the event payload, and a missing or failed lookup denies. The production CLI currently provides no authority-provider bootstrap by default: it remains **blocked**, not silently trusted. Live token/provider/capability binding composition is a separate protected operational acceptance dependency.
5. Existing synthetic tests explicitly set `BAOBAB_DEPLOYMENT_ENV=test`; a new PG17 end-to-end test proves the unapproved staging event remains BLOCKED without iDempiere writes, and a separate strictly synthetic authorised fixture exercises CP double checks, documentary double checks, provider readiness and one native order create.

## Still needed for actual live execution

- Provision protected IAM workload issuer/audience/scope for the worker and a current CP context+mandate/documentary assessor.
- Approve canonical provider-support capability mappings for order creation and bind them to a `NativeActionPolicy` in trusted deployment composition.
- Prove iDempiere AD_Client/AD_Org, seller/issuer, market/currency, audit correlation, lease recovery, DLQ and idempotent order adoption against a real protected staging engine.
- Validate no alternate direct posting/financial native paths across other modules; do not confuse CP's negative documentary veto or an injected policy with certified provider execution.

**No new canonical capability or real company fact is being registered. No production authority is granted by this PR. No Packages 5–8 or EA v2.1 are started.**
