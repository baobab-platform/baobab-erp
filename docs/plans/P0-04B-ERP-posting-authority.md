# P0-04B ERP — placement, provenance, posting authority and COMMIT fence

**Date:** 14 October 2026. **Shared pin:** `8733be2` (shared#304, ADR-SHARED-034). **CP counterpart:** baobab-cp#393.
**Governing:** ADR-ERP-022, ADR-SHARED-034, ADR-BCP-027 LA-05/LA-07. **Evidence gates:** EA v2.1 A–C on this PR;
Gate D (real iDempiere posting) is a separate harness PR and is required before atomic posting is claimed.

## What changes

1. **Native migrations** (`db/native-migrations`, `db/migrate-native.sh`; run after the iDempiere seed):
   - `N0001` maker/checker, append-only, non-overlapping `native_placement`;
   - `N0002` database-recorded `document_provenance` for every governed header, refusing unplaced orgs
     and org changes for placed clients;
   - `N0003` attribution lineage columns (decision, mandate lineage, placement, baseline, txid), an insert
     guard under the database clock, and deferred COMMIT fences on `Fact_Acct` and document completion.
2. **JVM** (`org.nabhold.baobab.erp.finance`):
   - `NativeOperationResolver` — ERP's table-to-operation policy (sales side only; purchase side and
     configuration denied);
   - `PlacementContextSource`, `BaselineFinanceReadiness` — the previously unimplemented trusted ports;
   - `CpNativeFinancialAuthority` — CP context for the placement, then the ADR-SHARED-034 decision
     (exact echo, placement's legal entity, ≤30 s lease), documentary veto, readiness, re-resolution,
     same-transaction attribution; bounded same-transaction reuse;
   - IAM scopes `context:resolve erp-posting-authority:resolve documentary:restriction-assess`.
3. **Contracts:** `erp/v2` request/decision in both runtimes, 22 conformance vectors, workload-scope assertion.

## Evidence

| Gate | Proof |
|---|---|
| A | `CpNativePostingAuthorityTest` (synthetic loopback CP: every acceptance and denial rule, no-CP denials, reuse), attribution, policy, wire, activator tests; Python conformance (erp/v2 vectors) |
| B | `NativeFinancePostgresGateBTest` in CI job `native-finance-postgres`: atomic commit, rollback, direct-SQL ledger/completion refused at COMMIT, expired and lapsing authority, no cross-transaction reuse, concurrent transactions, unplaced org, closed placement, purchase side, withdrawn baseline |
| C | `build-extensions`, `build-image` |
| D | **Open** — separate PR: real iDempiere 13 + PostgreSQL posting run |
| E | **Open** — operational acceptance, real placements/mandates, IAM admission |

## Not included

Real placements or mandates, workload activation, Python order-to-cash wiring, purchase-side and configuration
classes, costing-write classification, production enablement. Protected runtimes without CP/IAM configuration
continue to deny every protected financial write.
