# LA-05D7 — Native REST finance mutation guard (bounded increment)

**Authority:** Accepted ADR-BCP-026 and ADR-BCP-027, LA-05; ERP ADR-ERP-004, ADR-ERP-008 and ADR-ERP-016.

**State:** Code implemented for the Baobab ERP REST adapter; **not** proof of direct iDempiere JVM/UI/batch protection, statutory provider acceptance or operational readiness.

## What is enforced

The existing order-to-cash legal-actor, documentary and independent ERP provider assessments (LA-05D3–D6) establish an in-process, short-lived, operation-specific permit. The permit now includes the trusted `AD_Client_ID` and `AD_Org_ID`, not just tenant/actor/action/resource. A second gate in `integration.native_finance_guard` runs before any financial REST write in `RestIdempiereClient._call` and again in `_raw_request`, including retries.

* Direct creation of `C_Order`, `M_InOut`, `C_Invoice` and `C_Payment` requires the exact existing guarded operation and matching native client/organisation.
* Direct creation of finance configuration, journals, accounting facts, invoice/order lines and allocation objects is denied on this generic REST path.
* Updates/deletes of financial records are denied, including attempted `DocStatus`/posted-state rewrites; draft creation cannot inject posted/completed fields.
* Every native `/processes/{id}` mutation through this client requires the exact guarded action and its corresponding `IDEMPIERE_PROCESS_*` installation-specific configuration. Unrecognised processes, absent configuration and mismatched document IDs/action shapes are denied.
* A valid accounting issuer permit cannot be reused for payment posting or a different native company.
* Missing, unknown, staging and production runtime environments enforce the guard. The previous synthetic local test/development exemption remains explicitly configured and is overridden by `BAOBAB_REQUIRE_LEGAL_ACTOR_GATE=true`.

Neither request body nor process ID may supply the actor mandate, tenant authority or native company scope. The permit is revoked on wrapper exit, including failures, through `ContextVar` restoration. Tests use artificial actor and company IDs only.

## Boundaries and limitations

This is a **second ERP-side application PEP at the real REST egress**. It cannot intercept writes made *outside* Baobab's `RestIdempiereClient`: direct iDempiere REST credentials, iDempiere UI, imports, schedulers, document-process APIs or server-side accounting jobs. Those must be denied at network/identity exposure until an independently validated native iDempiere **ModelValidator/document-posting PEP**, server-side issuer evidence and company/readiness mapping are installed and tested against a real iDempiere instance.

The existing legacy ERP financial HTTP routes remain unavailable in protected environments without their own governed composition. No fake readiness, company, ledger, currency or legal evidence is created. No schema migration is needed for this increment because the action scope is ephemeral and no durable financial facts are changed.

## Remaining ERP native acceptance work

1. Install a server-side iDempiere before-completion/before-posting veto with non-optional enforcement for protected clients, including native UI/API, scheduled and import-origin documents, reversals and accounting adjustments. Validate plugin startup and deny semantics in protected integration tests.
2. Bind genuine IAM-issued ERP workload contexts, CP legal-actor/hold decisions and independently certified finance/company/period/currency/tax capabilities into the protected composition root. The currently missing live registration may only be activated through governed provider publication.
3. Persist immutable issuer/accounting-actor attribution and verified mandate reference on the accepted native document; reconcile with canonical mappings and events without rewriting historic posted books.
4. Verify native order adoption and line/company scoping, write/outbox recovery, double-post/idempotency and revocation races using real iDempiere and PostgreSQL in the protected staging environment.
5. Verify direct iDempiere entry-point lockdown, role assignments and the full negative LA-T06/08/10/14/20/23 matrix. Operational acceptance remains **BLOCKED** while AWS, IAM, real legal evidence, finance baselines and protected provider setup are unavailable.

This document makes no assertion that a production iDempiere provider is available, certified or permitted to post.
