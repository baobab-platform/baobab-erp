# ERP native ADR implementation and qualification ledger

Status: **engineering work in progress; no full native ADR acceptance or protected activation**.
Governing baseline: Accepted ERP ADR-001–020 and 022–023; ADR-021 is **Accepted on `main`** via ERP PR #133 (squash `7068382b4784`); production incorporation, Finance and CP approval remain independent. EA v2.3 / EA-DEV DEV-07/09/11/12/14.
Evidence custody: each gate requires exact source tuple, actual iDempiere 13 + PostgreSQL 17, native JVM/OSGi activation, positive AND negative cases and read-only independent database observations. Source tests are not substituted for business proof.

## Native capability inventory

| ADR | Current implementation foundation | Material native exit criteria still outstanding |
| --- | --- | --- |
| 001 | Pinned iDempiere 13 OSGi and disposable real-JVM Gate D | Independently operated, security-qualified EngineInstance and application services |
| 002 | Authoritative CP assignment parser, ERP placement, tenant map | Real governed ERP assignment, native role/org creation, real two-legal-entity readback |
| 003 | Company/org and placement fences, dedicated clients | Regional/data-residency deployment and second-region isolation evidence |
| 004 | Native context, events, mapping, finance, outbox, integration bundles | Protected OSGi lifecycle, compatibility, rollback/release proof |
| 005 | Restricted app-facing API and native acceptance bridge | Installed, authenticated production-worthy iDempiere REST OSGi routes and integration tests |
| 006 | Canonical outbox/inbox, replay, RabbitMQ, JVM consequence via merged ERP #125 | Original authorised Trade purchase event and live production consumer topology |
| 007 | Canonical/native mapping stores and native reverse context | CP-authorised creation, cross-client binding and lifecycle replay |
| 008 | Finance baseline, native period, live CP veto, ledger insertion fence, N0010 immutable history and N0011 configuration fences | Genuine balanced posted AR/AP/GL and reconciled multi-currency, intercompany, reversal and payment postings |
| 009 | Market/legal placement and finance configuration model | Source-qualified ZA/UG tax and currency packs, statutory testing, period management |
| 010 | Hydra, IAM/CP authority, live native actor/mandate controls | End-user/process/workload least-privilege testing, revocation, cross-client adversarial tests |
| 011 | Same-event exported OTel and independent readback, native attribution | Full BFF-to-native lineage, quantity/amount reconciliation, operational SLO alerting |
| 012 | Native PostgreSQL 17 restore drill, replay and immutable event keys | Real failover, PITR, bounded RPO/RTO, split-brain refusal and multi-company restoration |
| 013 | Pinned image and reproducible native migrations | Rehearsed promotion/rollback/upgrade with signed artifacts and security gate |
| 014 | Projection/master-data mapping and consumer identity | Native governed supplier/customer/product/warehouse create/update and conflict quarantine |
| 015 | Native receipt/order/invoice and purchase-costing accepted test paths | Qualified receiving/lot/quality/valuation/AP chain, supplier three-way match, exceptional and cross-border cases |
| 016 | Protected ERP Sales Order, durable Trade inbox, recovery and outbox | Authenticated buyer-origin event, native invoice/payment accounting, shipment/refund and reconciliation |
| 017 | Provenance, immutable evidence model and N0010 historic financial input fencing | Real private object-store custody, digest, scan/quarantine, retention and legal hold |
| 018 | Canonical event/projection abstractions | Governed financial reporting extracts with independently reconciled trial balances, tenant-filtered analytics, erasure |
| 019 | CP-directed provisioning worker and idempotent commands | Real native onboarding/credential issuance/deactivation, migration, rehome and revocation proof |
| 020 | Readiness evaluation with explicit fail-closed gates | Independent release evidence for each mandatory capability, full multi-company real golden paths |
| 021 | Accepted Pattern B UG/ZA ZuriBeans two-client design, merged in ERP #133; both ZuriBeans incorporations remain in progress | Verified incorporation and legal actors, Finance baseline, CP identifiers and independent native clients; no synthetic activation |
| 022 | Native placement, provenance, class catalogue, PostgreSQL COMMIT fences, N0010 history and N0011 configuration controls | Qualified reversal/bank/cash/manufacturing catalogue extensions only after Shared CP policy revision; do not widen classes locally |
| 023 | Baobab People/CDSoftware candidate on ERP #126 | Licence and compatibility audit, native OSGi/2Pack, statutory ZA/UG parallel payroll, approved posting and HR isolation |

## Gate sequence (no synthetic substitution)

1. **N0 — Native schema and history integrity.** Apply migrations 0001–0026 and N0001–N0013 to clean PostgreSQL 17; run PostgreSQL-backed finance Gate B including authorised posting, forbidden direct-SQL ledger edits/deletes, completed source/line changes, replay, wrong-client, expired decision, unplaced historical isolation. The *same exact versioned image* must complete the actual iDempiere Gate D test.
2. **N1 — Genuine transaction.** Provision legal buyer, seller, membership/site, budget, approved price signer and CP authority through their owning services. Independently read one non-draft Medusa order, seller commitment, buyer spend and the original immutable outbox event at one Trade PostgreSQL XID. Do not count synthetic events.
3. **N2 — Native ERP effect.** Dispatch original event by the existing RabbitMQ publisher; read it from the durable ERP inbox, CP decisions, genuine native C_Order, financial attribution and original unchanged event, including lost-result adoption without duplication.
4. **N3 — Accounting.** Follow native iDempiere source document processing through balanced posted Fact_Acct, AP/AR/stock/cost effects, accounting periods, documented FX and native reversal/credit controls. Compare GL and Trade/evidence totals independently. An ERP Sales Order alone does **not** qualify posting.
5. **N4 — Company and market.** Independently qualify distinct legal AD_Clients/AD_Orgs for UG and ZA only where real legal/Finance approval exists; deny tenant and company crossover, obsolete placement, revoked mandate and invalid accounting period.
6. **N5 — Documents and analytics.** Prove content custody, digest/retention/legal hold and authoritative ledger-derived exports with balance reconciliation; no direct operational database access from Pulse/BI.
7. **N6 — Recovery/operations.** Run real PostgreSQL restore/failover, outbox/inbox replay, correlation/exported-trace join, rematerialisation and independent teardown; record exact run/source hashes.
8. **N7 — Additional native capabilities.** Introduce manufacturing, bank/cash/reconciliation, native reversal, HR/payroll and other uncatalogued document families **only after** Shared erp/v2 operation classes and CP authority are accepted. The present explicit deny-by-name fences must remain intact meanwhile.

## N0010–N0013 safety boundaries

The new forward-only native migrations protect **ledger history** (Fact_Acct UPDATE/DELETE), **completed document source fields and DocStatus**, and **completed commercial/financial line values** from direct SQL tampering for any historically placed AD_Client. Draft line editing remains permitted; legitimate post-completion operational progress counters are not frozen. A placed document may not be deleted, even after a placement closes.

N0013 preserves historical AD_Client and AD_Org identities after the placement window closes. A closed placement may allow separate governed deactivation; it never permits deletion or reassignment of financial/actor identity or client IDs. New Gate B cases prove both closed-history refusal and open-placement deactivation refusal.\n\nN0012 also refuses TRUNCATE at the PostgreSQL statement boundary on native legal/financial history, document/line/accounting tables and evidentiary records. Row-level DELETE triggers cannot make this guarantee. The refusal is unconditional; governed retention/decommissioning must never silently truncate immutable history.

N0011 independently denies direct SQL changes to unapproved accounting schemas, schema GL/default accounts (`C_AcctSchema_GL` / `C_AcctSchema_Default`), charts/accounts, tax configuration and `C_Tax_Acct`, bank accounts and bank-account posting defaults (`C_BankAccount_Acct`) for historically placed clients, including cross-client reassignment. The iDempiere 13 exact native name is `C_Tax_Acct`, not `C_TaxAcct`; earlier real-JVM acceptance refused the bad identifier and drove this correction. There is no new CP authority class, and iDempiere system-client configuration remains a separately governed release responsibility.

This is deliberately *not* a replacement for the native OSGi financial veto, CP posting-authority assessment, N0003/N0006 deferrable insertion/completion fences, the legal-actor approval process or a financial reversal operation. There is no arbitrary raw-SQL posting pathway or new authority grant.

**Release posture:** Until N0 is qualified at the PR's final head, this is an integration candidate only. Even after N0, N1–N7 remain independently gated; L4-OPS-01 and protected activation stay BLOCKED.

## 12 November 2026 — latest final-head S04b adjudication and safe remediation contract

**Source evidence:** PR #132 final-head `9e382f1e509f779b7d8c3881f75dcd062db646e4`, real ERP-A run [43163677209](https://github.com/baobab-platform/baobab-erp/actions/runs/43163677209), failing ERP-A job `131000456884`, and companion real Hydra/CP/RabbitMQ/JVM run [43163677318](https://github.com/baobab-platform/baobab-erp/actions/runs/43163677318), failing job `131000456756`. Native PostgreSQL/financial Gate D and other CI suites on that head passed, but ERP-A and DEV-11 **failed**. Do not conflate a passing journal test with posted purchase-side invoice matching.

**Exact independently observed S04b:** `M_MatchInv_ID=1000000`, `Posted='E'` before/after readback, `Fact_Acct=4` already present and balanced, invoice-line `M_CostDetail=2`, derived attributions `=4`, `posting_attempted=false`, `native_error_class=POSTING_STATE_CONFLICT_WITH_COMMITTED_FACTS`. The driver deliberately declines a forced `Doc.post` against committed history; the accounting status and ledger/derived rows are **inconsistent**. It is incorrect to set `Posted=Y`, ignore S04b, disable N0010 or delete committed `Fact_Acct` to make the gate green.

**Required solution investigation (before any merge):**

1. **Actual iDempiere lifecycle inventory:** independently trace the exact first-post/reprocessing entry points for `M_MatchInv`, `C_Invoice`, `M_InOut`, `M_MatchPO` and their `M_CostDetail` side effects in the selected upstream 13 OSGi binaries and transaction boundaries. Record when committed facts already exist and which native action invokes `Doc.deleteAcct`.
2. **Evaluate a supported non-destructive native sequence first.** If native receipt/invoice/match creation can be committed in an order that produces `M_MatchInv.Posted='Y'` on its **first** authorised post, prove this with original source documents, current CP operation/actor mandate, independently committed status and balanced ledger, idempotent replay and no temporary historic row rewrite. Do not treat changing test order alone as proof of valid business execution.
3. **If correction is genuinely required, design a governed compensating operation.** Add the minimal accepted versioned Shared `erp/v2` corrective/reversal operation class, permitted source-family semantics and CP legal-actor/role/spend/period mandates. Implement through supported native iDempiere extensions and a separate immutable reversal/correction evidence chain; do not expose arbitrary SQL, unrestricted table updates or an unbounded period re-open. No new operation class is authorised in this PR.
4. **Independently verify on real PostgreSQL 17 + iDempiere 13:** original `Fact_Acct` row identities/checksums unchanged; append-only correction if permitted; no WIP/inventory or AP double recognition; clear `M_MatchInv` posting semantics and journal balance; durable CP attribution, original source and exported trace; two-company/closed-period negatives; failed, repeated, late and committed-result-loss recovery.
5. **Maintain a hard release gate:** S04b `Posted='Y'`, independently balanced and reconciled source facts, cost rows and attribution must pass at the exact final head **together with** native Gate B, Gate D, ERP-A and connected DEV-11; otherwise ERP #132 stays DRAFT/HOLD. A test-only bypass, fake `Posted=Y` or broad N0010 exception is prohibited.

**No qualified compensation or upstream-supported alternate lifecycle is yet demonstrated.** ERP #132 remains a useful protected-history implementation candidate, not a merged production-ready financial correction facility. Its existing N0010 same-transaction provisional-`xmin` rollback exception remains narrowly scoped to uncommitted rows and shall never become permission to destroy historical committed facts.
