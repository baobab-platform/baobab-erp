# P0-04B ERP — placement, provenance, posting authority and COMMIT fence

**Date:** 14 October 2026. **Shared pin:** `8733be2` (shared#304, ADR-SHARED-034). **CP counterpart:** baobab-cp#393.
**Governing:** ADR-ERP-022, ADR-SHARED-034, ADR-BCP-027 LA-05/LA-07. **Evidence gates:** EA v2.1 A–C on this PR;
Gate D (real iDempiere posting) is a separate harness PR and is required before atomic posting is claimed;
it also fixed three defects that only a real runtime exposed (ADR-ERP-022 §7).

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
| D | CI job `idempiere-posting-integration` (`idempiere/acceptance/run-gate-d.sh`): real iDempiere 13 + PostgreSQL GL-journal posting through the shipped veto and COMMIT fence. Certified only from a green CI run of that job, recorded in the receipt |
| D (P0-04B-05) | Same job, extended to the sales flow: sales order, shipment with derived costing, customer invoice, receipt and allocation. Each class has valid and denial scenarios, plus receipts-only and sales-only enforcement and direct-SQL costing fences (ADR-ERP-022 §4.1–4.2) |
| E | **Open** — operational acceptance, real placements/mandates, IAM admission |

## Not included

Real placements or mandates, workload activation, Python order-to-cash wiring, purchase-side and configuration
classes, costing-write classification, production enablement. Protected runtimes without CP/IAM configuration
continue to deny every protected financial write.

## ERP-A — purchase side and vendor-payment recording (EA v2.2 EA-R03, 2026-10-15)

Shared `erp/v2` catalogue version 2 (ADR-SHARED-037, Shared#314, pinned at `756edb4`) adds five recording
classes. ADR-ERP-022 §4.3 records how ERP classifies them.

| Layer | Change |
|---|---|
| Native migration | `N0006`: `governed_class_of` / `governed_root` / `allocation_line_side` as the single classification rule; class-exact `has_current_attribution_for`; `Fact_Acct` fence routed through a matching row's root; deferred COMMIT fences on `M_MatchPO` / `M_MatchInv`; payment selections refused outright for placed clients; class locks on `M_InOut.MovementType` and outbound `C_Payment.IsOnline` |
| JVM | `NativeOperationResolver` classifies headers from their own values and stored documents through `governed_class_of`; matching rows classified as their root; empty draft allocation headers carry no decision; `M_MatchPO`, `M_MatchInv` and `C_PaySelection*` are protected tables; same-transaction reuse is class-exact |
| Contracts | Shared pin `92541c9` → `756edb4`; both runtimes re-synced (`sync_authority_contracts.py --check`) |

**Evidence (this PR).**
- **Gate B.** `NativeFinancePostgresGateBTest` runs 29 tests on PostgreSQL 17. The CI job moves from PostgreSQL 16 to 17. The new tests cover:
  - purchase classification by own values and stored rows, with vendor returns and AP credit memos denied;
  - purchase completion only under its own class;
  - class-exact reuse;
  - payment selection refused, and online switching locked;
  - no AP/AR netting, with a direct-SQL sales line refused on a payables allocation;
  - matching fenced through its root on insert, ledger posting and delete.
  - review fixes (Codex on #100): allocation documents must belong to the allocation's client; re-pointing a match needs both the old and the new root's authority; payment-selection rows cannot move into or out of a placed client; an allocation's last line is deleted only with its own side's authority.
- **Mutation check.** Removing the `M_MatchPO` fence and the `C_PaySelection` trigger fails the two corresponding tests. Reverting each of the four review fixes fails its own test.
- **Gate A and C.** The finance unit tests and the `erp/v2` conformance tests (89) pass, and the packaged JAR verifies (167 wire vectors).

**Not in this PR.**
- Purchase-side costing (receipt and match cost details) stays denied until real iDempiere shows which writes are deterministic root consequences.
- The engine-local harness (real iDempiere 13, the real CP binary at a pinned merged SHA, real signed workload tokens, PostgreSQL 17, crash-window and bypass scenarios) is the next ERP-A PR. Gate D's synthetic CP knows only the version 1 classes, so its outbound-payment scenario still denies here; that PR rewrites it against the real CP.
- Engine-local evidence on synthetic data is **not EA Gate D and not L4** (EA v2.2 §§3, 7). Production stays denied.
