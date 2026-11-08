# Baobab People — permanent Bring Your Own Provider (BYOP) architecture

**Owner direction: 8 November 2026. Design intent approved in ERP ADR-ERP-023 Addendum B; implementation, Shared contracts, CP bindings, statutory verification and protected release are NOT approved.** Companion Shared proposal: [Shared #434](https://github.com/baobab-platform/shared/pull/434).

## Product promise

Baobab People is an **optional, first-party product within baobab-erp**, not a prerequisite for Baobab tenancy, Trade, CMS, CRM, finance or any unrelated service. A tenant that already uses a suitable HRIS or payroll bureau may retain it indefinitely. We compete through value and interoperability, never forced migration. Provider-neutrality covers workforce records, time, leave, benefits, payroll calculation, payslip, statutory filing and evidence; it is **not limited to payroll's initial fallback provider**.

- **Native**: an employer explicitly chooses a qualified Baobab People implementation for certain functions.
- **Existing provider (BYOP)**: the legal employer retains an independently qualified in-house system, third-party service or bureau as the authoritative source for its allocated functions.
- **Hybrid**: the employer chooses providers independently by function; for example, external HRIS and payroll, Baobab reporting of lawfully permitted aggregate cost-centre values, or native attendance with external payroll.
- **External-only**: no native People activation, native iDempiere journal or Baobab Payments release is demanded where the tenant has not requested those specific capabilities.

None is inherently more privileged, legally qualified or production-ready than another. The choice requires independently attested tenant/employer authority; no runtime configuration or qualification is implemented by this design document.

## Ownership and authority matrix (target semantics)

| Function/data | Authority when native People is selected | Authority when an existing provider is selected |
| --- | --- | --- |
| Tenant, legal employer, market, grants, provider bindings | CP; IAM for identities and sessions | **Same CP/IAM boundary** for Baobab operations; tenant's external system may govern its own operations independently |
| Employment history / employee profile | Qualified native People, limited by employer permissions | Named existing HRIS; Baobab only lawful minimal projections, if opted in |
| Attendance / leave decisions | Qualified selected native function | Tenant-selected attendance/leave provider; not automatically overwritten by People |
| Payroll run calculation / final result | Qualified native engine and jurisdiction pack | **Exactly one designated qualified external payroll result per run/version**, with signed source/provenance |
| Payslips, returns, employee documents | Explicit selected custody/filing provider | Selected existing provider; no automatic transfer of restricted employee content |
| Journal / liabilities | Native iDempiere **only if that ERP capability is expressly used**, always with native veto | External accounting may remain authoritative; a requested import to iDempiere must pass its normal posting veto |
| Payment, bank release, settlement | Separately authorised payment/treasury provider | External disbursement remains external; never imply Baobab Payments execution |
| Legal/statutory qualification | Country- and provider-specific expert review | Same standard; being an existing supplier is not certification |

## Proposed provider-selection contract — do not register as a live capability

Any future accepted Shared schema must represent these **semantic dimensions**, without requiring vendor-shaped IDs:

- CP-issued tenant and exact legal-employer identifiers; separately specified market, work jurisdiction and statutory/tax jurisdiction where applicable.
- Requested **capability/function**, selected provider identity and private adapter reference; qualification digest and qualifications for that jurisdiction, regime, product version and effective window.
- Binding revision, active/revoked/suspended status, start/end effective time, role/mandate and lawful-purpose constraints; access to one function must not imply access to every employee record.
- Source-of-record designation for each domain and immutable run/version, with allowed read-only projections; signed input receipt/result, original provider correlation, idempotency key and loss/duplicate-replay policy.
- Historical ownership, versioned correction/rollback and export format, retention/destruction policy, custodians and observed cutover/reconciliation decision.
- Prohibited conditions: implicit provider default, unqualified production route, automatic failover to native People, silent dual-write, cross-employer/sibling access, vendor ID in a canonical entity key, external approval treated as native posting/payment permission.

**Adapter ports** should express capability-neutral operations (read authorised employment snapshot; submit/receive scoped payroll evidence; read status; request qualified reconciliation), not raw vendor endpoints. An adapter may use API, signed events, encrypted files or independently attested manual evidence if explicitly evaluated. Unsupported operations return a closed, typed refusal; adapters never infer a successful pay run from message delivery or locally forged approval flags.

## Provider onboarding and switching — expected gates

1. **Choose**: legal employer selects each function's source of record and whether Baobab is allowed a projection; tenant choice is not copied to related companies.
2. **Qualify**: verify vendor integration/security, processing agreement, regulatory permissions, applicable ZA/UG statutory scope, credential custody, segregation of duties and a signed reproducible result. A supplier relationship is not evidence of qualification.
3. **Bind**: CP writes governed employer/function/jurisdiction/effective-window provider binding, only with current IAM principal and mandate; no branch-only or schema-only activation.
4. **Operate**: source events and receipts carry immutable IDs, expected version and original provenance. Validate external identity, current binding, legal purpose and payload before any Baobab projection or native financial consequence.
5. **Change/exit**: create effective-dated cutover; freeze old source writes at the agreed boundary, reconcile outstanding runs, preserve audit and correction ownership; revoke old credentials only after independent receipt of exported tenant data. No historical pay run may silently switch calculators or be re-finalised in both systems.
6. **Recover**: treat outage, missing records, unknown results and asynchronous replay as distinct states. No silent source-of-record failover, repeat bank instruction or fabricated filing receipt.

## Acceptance catalogue (to execute after accepted contracts/adapters)

| ID | Expected independently observed outcome |
| --- | --- |
| BYOP-01 | Existing external HRIS + payroll retained; no native People/ERP/Payments activation; other Baobab capabilities unaffected |
| BYOP-02 | Native People for one function; qualified external provider for another; no implicit shared employee-data rights |
| BYOP-03 | Two employers within one tenant select different providers; wrong employer cannot read/commit another employer's data |
| BYOP-04 | Same employer changes provider by effective window; immutable prior run/version still resolves to original authority |
| BYOP-05 | Revoked/expired CP binding, IAM grant or processing purpose refuses the requested provider operation |
| BYOP-06 | Duplicate webhook, replay and committed-result loss do not create duplicate ledger entries, payruns, filings or payments |
| BYOP-07 | Provider outage produces explicit pending/unknown; no automatic native fallback or invented success |
| BYOP-08 | Conflicting native/external results for same run/version are rejected; parallel comparison is read-only |
| BYOP-09 | Signed file/manual import lacks authenticity, provenance or qualified jurisdiction: fails closed, no staff-data leakage |
| BYOP-10 | Lawful export and migration-out independently verified; balances, corrections, retention and audit custody reconciled |
| BYOP-11 | Inbound aggregate journal subject to native iDempiere employer, mandate, balanced-entry and closed-period veto |
| BYOP-12 | External bank payment remains external; no inference of Baobab Payments approval or settlement |

## Current engineering gap — do not misrepresent readiness

ERP #126 has only experimental append-only employer versions and payroll *draft metadata* in a disposable PostgreSQL 17 environment. Its `VerifiedCalculation` eligibility checks a signed-qualification abstraction but does **not yet** enforce a CP-owned tenant-selected provider binding or make a real authoritative payroll result. There are no accepted Shared People API schemas, approved external adapters, vendor-held employee-data custody, native payroll post, certified statutory packs or successful protected BYOP scenarios. This design must not be used to mark a capability Supported, Qualified or Activated.

Keep the proposed Shared obligations in `shared/proposals/people-contracts/` outside the canonical catalogue. This document and architecture regression tests are non-activating; BP-04's existing experimental migration and provider-fence protections remain unchanged.
