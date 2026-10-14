# ADR-ERP-022 — Native Placement, Document Provenance and Posting-Authority Enforcement

**Status:** Accepted (platform owner decision, 2026-10-14)  
**Decision class:** ERP / Legal actor / Accounting execution / Native enforcement  
**Scope:** `baobab-platform/baobab-erp`  
**Parent ADRs:** ADR-ERP-002 (tenant ≠ AD_Client), ADR-ERP-008 (Finance-approved baseline), ADR-ERP-021 (placement is ERP's decision)  
**Platform ADRs:** ADR-BCP-027 (§4.2, §6.1, §8.3, §9, §10.2, LA-05, LA-07), ADR-SHARED-034 (`erp/v2` posting authority)  
**Date:** 2026-10-14

---

## 1. Decision

An accounting operation in iDempiere is permitted only when two independent authorities agree, inside the
operation's own database transaction:

| Question | Authority | Where |
|---|---|---|
| Which operating Organisation, legal entity, tenant and market does this native org represent? | ERP native placement, maker/checker approved | `baobab_native.native_placement` |
| Which operating Organisation created this document? | Document provenance, recorded by the database at creation | `baobab_native.document_provenance` |
| May that Organisation's legal actor perform this operation now? | Control Plane, per operation | `/internal/erp/v1/posting-authority/resolve` (ADR-SHARED-034) |
| Is the company, Finance baseline and period ready? | ERP | `BaselineFinanceReadiness` |
| Is a documentary restriction in force? | Control Plane, negative only | PEO-02T |

A placement never creates authority. CP must name the placement's own legal entity; a holding-company
placement cannot post for an operating business without that business's mandate (ADR-BCP-027 §4.2 #11).

## 2. Placement

`native_placement` is append-only and versioned. Each version records tenant, engine instance, operating
Organisation, legal entity, market, AD_Client/AD_Org, effective window, two distinct named humans
(`approved_by`, `checked_by`), evidence and the CP ERP assignment it follows. Windows for one native org
never overlap and versions never change their CP identity. The only permitted change is closing an open
window once, never into the past. A placement is never inferred from AD_Org names, a tenant default or
group ownership.

## 3. Provenance

An AFTER INSERT trigger on every governed header (`GL_Journal`, `C_Invoice`, `C_Payment`, `C_AllocationHdr`,
`M_InOut`, `C_Order`, `C_BankStatement`, `C_Cash`) records the placement in force for a placed client's
document, for every route (UI, REST, import, scheduler, SQL). A placed client cannot create a governed
document in an unplaced org, and a governed document cannot change client or org. Later writes use the
creation placement, or a later version of the same placement with unchanged identity; anything else is
ambiguous and denied.

## 4. Classification

ERP alone maps native writes to Shared operation classes: headers by table (sales side only for invoices,
shipments and orders; receipts only for payments), lines by their header, ledger lines (`Fact_Acct`) by
`AD_Table_ID`/`Record_ID`, cost details by their root (§4.2). Purchase-side documents, outbound payments,
bank statements, cash journals and accounting configuration (schema, chart, tax, bank accounts) have no class
yet and stay denied in protected runtimes. No vendor identifier crosses the Shared boundary.

### 4.1 Direction (amendment, P0-04B-05, owner decision 2026-10-14)

Permission to record money received is not permission to disburse it, and sales-side authority never covers
purchases. A `C_Payment` classifies as `erp.payment.record` only when its own value, and for an existing
payment its transaction-visible stored row, has `IsReceipt='Y'`; a missing or `'N'` value denies on every
route (header, lines, `Fact_Acct`, repost, scheduled processing). An allocation classifies only when every
line joins a sales invoice and a receipt. `C_BankStatement` and `C_Cash` no longer map to `payment.record`.
In the database (N0005), completion and ledger posting require an attribution of the source table's **own**
class with the governed direction still holding at COMMIT, and a governed document's `IsReceipt`/`IsSOTrx`
cannot change. Vendor disbursement needs a separate catalogued operation (for example
`erp.vendor-payment.disburse`) with its own legal actor, activity and payment controls.

### 4.2 Derived costing writes (amendment, P0-04B-05, owner decision 2026-10-14)

> A native costing write MAY inherit authorization from a catalogued root ERP operation only when ERP proves
> that the costing write is a deterministic consequence of that operation within the same database
> transaction and under the same native placement, provenance and legal-actor attribution. Costing writes
> without such provenance are denied. Independent costing or revaluation operations require their own
> catalogued authority.

`M_CostDetail` and `M_Cost` are iDempiere implementation structures, not Baobab operations, and never earn
their own CP decision. iDempiere writes a sales shipment's cost detail while posting it
(`Doc_InOut.createFacts` → `MCostDetail.createShipment`, `M_InOutLine_ID` and `IsSOTrx` set) and then updates
the aggregate `M_Cost` in the same transaction. ERP therefore classifies a cost detail as the
`erp.shipment.complete` operation of the sales `M_InOut` its single source line belongs to (same client; its
org or 0), reuses that root's current same-transaction attribution, or obtains the root's own decision, and
appends an immutable `derived_write_attribution` row bound to it. `M_Cost` is allowed only when this
transaction already derived a cost detail for the same client, product and schema. N0005 fences both tables
at COMMIT. Material receipts, inventory, movement, production, landed cost and cost adjustment or
revaluation stay denied until catalogued.

## 5. Freshness and atomicity

The JVM veto appends the attribution (CP decision, mandate lineage, placement, baseline) in the SAME
transaction before the native write. Deferred constraint triggers re-check at COMMIT that a placed client's
`Fact_Acct` rows and document completions (DocStatus → CO/CL) are covered by a current attribution of the
same transaction. A CP decision is usable until `min(expires_at, ERP receipt + 30 s)`: a revocation takes
effect within 30 seconds, and a transaction that outlives its authority rolls back whole. Database atomicity
and CP freshness are separate guarantees; both are required (OWASP authorization-data guidance: bound
propagation, deny when the bound cannot be met).

Within one transaction a still-current attribution for the same source document covers further writes
(lines, ledger lines) without new CP calls: an exact-match, bounded reuse that never crosses transactions.

## 6. Deployment order

`db/migrate.sh` (application schema, 0025) → iDempiere seed/upgrade → `db/migrate-native.sh`
(N0001–N0005; refuses without the adempiere schema) → start iDempiere with the finance bundle → expose routes.
Every governed `AD_Client` must use **standard** period control (`C_AcctSchema.AutoPeriodControl = 'N'`):
Baobab readiness governs periods through `C_PeriodControl`, and under Automatic Period Control iDempiere
rewrites `C_AcctSchema.C_Period_ID` from `MPeriod.isOpen` in its own transaction, a configuration write the
native veto refuses, so every completion would be denied.
The native migrations must target the SAME database iDempiere uses. Grant the iDempiere role INSERT/SELECT
on `baobab_native`; never UPDATE/DELETE or BYPASSRLS.

## 7. Evidence standard

Gate A (unit), B (PostgreSQL: `native-finance-postgres`) and C (bundle build) run on every PR. Atomic posting
is **not** certified until Gate D, a real iDempiere/PostgreSQL posting run, passes; production stays denied
until Gate E operational acceptance. Synthetic fixtures are never evidence of legal standing.

Gate D is the CI job `idempiere-posting-integration` (`idempiere/acceptance/`): the deployable image plus a
CI-only driver bundle posts real GardenWorld GL journals on a fresh database against a synthetic CP over TLS,
and asserts persisted state (DocStatus, balanced `Fact_Acct`, attribution rows) for every scenario in the
owner's proof standard. Its first runs found three defects that Gates A–C could not see, all fixed in the same
PR: integer-typed native triggers against iDempiere's `NUMERIC(10)` ids (N0004; the Gate B fixture now uses
the real types); the JVM veto registered through `ModelValidationEngine.addModelChange` with client 0, which
iDempiere keys per client so it **never fired for a real client** (now a synchronous OSGi `EventHandler` on
the BEFORE topics, see LA-05D8); and the automatic-period-control configuration write above.

## 8. Consequences and open items

- Real placements, mandates and IAM workload admission are owner actions.
- Purchase-side and configuration operation classes need a Shared catalogue revision (ADR-SHARED-033 keys).
- Costing caused by a sales shipment is a derived write (§4.2); every other costing origin stays denied until
  it has its own catalogued class. Gate D covers GL journals and the sales flow (order, shipment with costing,
  customer invoice, receipt, allocation) as of P0-04B-05.
- Bank reconciliation, the cash journal and vendor disbursement need Shared catalogue revisions (§4.1).
- The Python order-to-cash layer is not yet wired to this path.
