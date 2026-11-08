# ADR-ERP-021 — ZuriBeans Multi-Market AD_Client Topology

**Status:** Accepted — 8 November 2026; authoritative ERP topology decision. Incorporation, CP provisioning, Finance approval and production activation remain independently gated.  
**Decision class:** ERP / Tenancy / Canonical Mapping / Organisation Model  
**Scope:** `baobab-platform/baobab-erp`, `baobab-platform/baobab-cp`, `baobab-platform/zuribeans`  
**Parent ADR:** ADR-ERP-002 — ERP Tenant, Client and Organization Mapping  
**Related:** ADR-ERP-008 — ERP Financial, Accounting and Multi-Currency Architecture; ADR-ERP-019 — ERP Provisioning, Tenant and Legal-Entity Onboarding, Migration and Decommissioning Architecture; `zuribeans/docs/adr/ZuriBeans Go-Live Implementation Plan` Gate ZB-16  
**Date:** 2026-09-16 (proposed); **Accepted:** 2026-11-08 (owner's architecture decision)

---

# 1. Decision

ZuriBeans has business footprints in **Uganda and South Africa**. Incorporation
of the relevant companies remains **in progress** at acceptance. A country
footprint is not evidence of incorporation, legal capacity, tax registration
or permission to trade; neither entity is represented here as incorporated.

ADR-ERP-002 §28 and ADR-ERP-008 §179 explicitly forbid inferring a multi-market
tenant's `AD_Client`/`AD_Org` topology from country codes or defaulting it.
**This accepted ADR is the explicit, binding architecture choice for ZuriBeans.**
ERP, ZuriBeans and CP implementation proposals SHALL conform to it unless a
later accepted ADR revises the topology.

ZuriBeans SHALL be represented, **when independently qualified for legal-entity
onboarding**, as **two separate iDempiere `AD_Client`s**, one per country.
The following are reserved **architecture identifiers**, not claims of
already-registered companies or provisioned production clients:

```text
ZURIBEANS_UG   — ZuriBeans Uganda,      LegalEntity: zuribeans-ug
ZURIBEANS_ZA   — ZuriBeans South Africa, LegalEntity: zuribeans-za
```

This is ADR-ERP-002 §28's "Pattern B" (as opposed to Pattern A: a single `AD_Client` with markets
represented as `AD_Org`s or accounting dimensions). Both `AD_Client`s SHALL share the approved logical
`ERP-AF-SOUTH-01` `EngineInstance` topology alongside `NABHOLD` and
`THAMANI`'s own Clients, per ADR-ERP-002 §131's
default shared-instance topology and ADR-ERP-019 §27/§242's sanctioned rollout order — this is an
operational choice (fewer EngineInstances to operate), not an architectural requirement to isolate further;
a dedicated `EngineInstance` per Client remains available later if residency or isolation requirements
change (ADR-ERP-002 §13).

Each eventual `AD_Client` SHALL resolve to its **own verified CP `LegalEntity`**,
its own separately authorised `CapabilityBinding`, and its own independently
Finance-approved accounting configuration (functional currency, chart of
accounts, fiscal calendar and tax profile) per ADR-ERP-008 §19/§177. None
shall be inherited, copied or defaulted from the other market. The logical
EngineInstance label cannot substitute for a real CP-issued identifier.

---

# 2. Why this decision was needed

ZuriBeans' provisioning template (`config/provisioning/zuribeans.production.template.json`, prior to this
ADR) had a single `legal_entity_id` field with two `markets` entries nested underneath it — structurally
Pattern A, chosen implicitly by the shape of a config file rather than as a documented architectural
decision. ADR-ERP-002 §28's closing sentence is explicit that this choice "must be an explicit, documented
choice... not a default," and ADR-ERP-008 §179 makes the same point for the accounting consequence:
"expanding into a second market... does NOT automatically mean 'Market = its own ledger.'" Gate ZB-16 of
the ZuriBeans go-live masterplan cannot be implemented — not even the provisioning request shape — without
this being settled first, since every downstream artifact (the provisioning config, the `AD_Client`/`AD_Org`
resolution the context bundle performs, the accounting-schema configuration ADR-ERP-008 requires per
LegalEntity) depends on knowing whether ZuriBeans is one LegalEntity or two.

---

# 3. Consequence: intercompany trade between ZURIBEANS_UG and ZURIBEANS_ZA

Choosing two `AD_Client`s makes ZuriBeans UG ↔ ZuriBeans ZA an
**intercompany** relationship once both separate legal entities are verified,
onboarded and independently authorised to transact; the existence of market
footprints alone is insufficient (the masterplan's Gate ZB-11, "Internal Cross-Market Trade," and its
"same legal entity?" branch resolves to NO for ZuriBeans specifically). ADR-ERP-008 §92-97 already governs
this:

- No cross-`AD_Client` SQL transactions to simulate intercompany accounting (INV-ERP-FIN-030).
- Each entity represents the other as its own `C_BPartner` — `ZURIBEANS_ZA` is a business partner record
  inside `ZURIBEANS_UG`'s Client, and vice versa, not a shared row.
- Intercompany trade between them is real Purchase Order / Sales Order pairs plus AR/AP, settled and
  eliminated like any other intercompany relationship in the platform — not a special-cased shortcut for
  being "the same company."

This is recorded here as a direct consequence of Pattern B, not designed in this ADR — implementing the
UG↔ZA intercompany flow is explicitly out of scope for the accounting-spine increment this ADR unblocks
(see the go-live gate audit's ZB-16 implementation notes) and is follow-up work.

---

# 4. Alternative considered and rejected

**Pattern A — single `AD_Client ZURIBEANS`, UG and ZA as `AD_Org`s or accounting dimensions within it.**
Rejected for ZuriBeans specifically (though it remains architecturally valid for other tenants under
ADR-ERP-002 §28) because:

- ZuriBeans Uganda and ZuriBeans South Africa are **intended to become
  separately incorporated legal entities**, with independent jurisdiction,
  functional currency (UGX versus ZAR), tax and statutory reporting. **Both
  incorporation processes remain in progress**: no registered company number
  or completion is asserted. ADR-ERP-008 §19 ties these obligations to the
  `LegalEntity` level, not to the `AD_Org` level.
- A single shared `AD_Client` would require either collapsing two functional currencies into one accounting
  schema (which ADR-ERP-008 §20 does not support — one functional currency per `AccountingSchema`) or
  running two `AccountingSchema`s under one Client, which is a materially more complex configuration than
  two Clients for no isolation benefit.
- Two `AD_Client`s give ZuriBeans UG and ZuriBeans ZA the same isolation guarantees Nabhold's other
  multi-entity tenants already get (ADR-ERP-002 §15's rejected-alternative note for the group-wide case
  applies here too, at ZuriBeans' own scale).

---

# 5. Invariants

- **INV-ERP-TOPO-001** — `ZURIBEANS_UG` and `ZURIBEANS_ZA` SHALL be provisioned as two distinct
  `AD_Client`s, never one Client with two `AD_Org`s standing in for the two countries.
- **INV-ERP-TOPO-002** — No SQL transaction SHALL span both Clients; cross-Client consequences flow only
  through the canonical event/outbox mechanism (ADR-ERP-004 §44-51) or explicit intercompany documents
  (ADR-ERP-008 §92-97), never direct database access.
- **INV-ERP-TOPO-003** — Each Client's `LegalEntity`, functional currency, chart of accounts, fiscal
  calendar and tax profile SHALL be configured and approved independently, only after legal incorporation
  evidence and CP mapping verification; neither is copied or defaulted from
  the other.
- **INV-ERP-TOPO-004** — Both Clients SHALL resolve to the same `EngineInstance` (`ERP-AF-SOUTH-01`) unless
  a future ADR records a residency or isolation requirement that necessitates separating them, per
  ADR-ERP-002 §13's isolation escalation path.
- **INV-ERP-TOPO-005** — The ZuriBeans provisioning configuration SHALL be two independent
  `ErpProvisioningRequest` documents (one per Client), never a single request carrying two `markets` entries
  under one `legal_entity_id`.

- **INV-ERP-TOPO-006** — Business presence and acceptance of this ADR
  SHALL NOT be treated as evidence that either company has been incorporated,
  tax-registered or authorised to trade. The Uganda and South Africa
  production provisioning templates SHALL remain `draft-not-approved` until
  verified legal records, current CP identifiers and Finance sign-off exist.
- **INV-ERP-TOPO-007** — Acceptance of this architecture authorises engineering
  implementation and synthetic/disposable qualification only. It SHALL NOT
  mint a legal mandate or capability binding, activate a provider, allow
  production financial posting, or waive IAM/CP, Finance, statutory, residency
  or EA-09 approvals.
- **INV-ERP-TOPO-008** — A materially different eventual legal-entity
  structure SHALL stop production provisioning and require a reviewed,
  accepted ADR revision, not silent consolidation into Pattern A.

---

# 6. Final decision statement

```text
                    ZURIBEANS (BAOBAB CANONICAL TENANT)
                                  │
                 ┌────────────────┴────────────────┐
                 │                                  │
         LegalEntity: zuribeans-ug          LegalEntity: zuribeans-za
                 │                                  │
                 │ explicit, scoped mapping         │ explicit, scoped mapping
                 ▼                                  ▼
       AD_Client: ZURIBEANS_UG              AD_Client: ZURIBEANS_ZA
       Functional currency: UGX             Functional currency: ZAR
                 │                                  │
                 └──────────── shared ───────────────┘
                          EngineInstance:
                          ERP-AF-SOUTH-01
```

Two Clients, one shared instance, independently configured accounting. The relationship between them is
intercompany, not internal-to-one-entity — governed by ADR-ERP-008 §92-97, not invented here.

---

# 7. Acceptance and legal-onboarding gates (8 November 2026)

**Architectural authority — ACCEPTED.** Pattern B is binding for ZuriBeans:
two separately governed legal-entity-scoped iDempiere `AD_Client`s,
independent UGX/ZAR finance configurations, and the shared *logical*
`ERP-AF-SOUTH-01` EngineInstance unless a later accepted isolation or
residency decision supersedes it. No downstream ERP, CP or ZuriBeans
implementation may silently collapse these into one Client or infer the
topology from market data.

**Legal factual state — INCORPORATION IN PROGRESS.** ZuriBeans has
footprints in Uganda and South Africa, but incorporation of the intended
companies is not yet complete. `zuribeans-ug` and `zuribeans-za` are
reserved conceptual legal-entity mapping identifiers, **not** verified
registry numbers, current CP LegalEntities or existing production
`AD_Client` records. Do not invent legal names, incorporation numbers,
tax registrations, signing mandates or a CP-issued ID.

**Engineering permitted immediately:** retain and implement separate
Uganda and South Africa request shapes; develop canonical mappings,
strict tenant isolation, independent native finance boundaries, and
disposable development/acceptance simulations with visibly synthetic
identities and negative intercompany tests.

**Protected operational execution stays blocked until each company has:**

1. Independently verified incorporation record, actual legal name, national
   registration and applicable tax/customs/payroll or other statutory
   registrations, legal-actor capacity and permitted market activities.
2. Actual CP-issued Tenant, LegalEntity, Market and EngineInstance
   identifiers, authoritative legal-actor/mandate evidence, and explicit
   mapping to its own iDempiere `AD_Client` and `AD_Org`; no fabricated
   or inherited identifiers.
3. Independently approved Finance configuration: functional currency,
   chart of accounts, accounting schema, fiscal calendar, tax/localisation,
   costing policy and controlled native financial-posting authority.
4. Separately qualified CP capability bindings, isolation/residency
   checks, live native iDempiere acceptance evidence and required EA-09
   protected deployment approval. Intercompany UG ↔ ZA purchase/sale,
   AR/AP, settlement, FX and consolidation/elimination require an
   additional qualified business execution path.

The two existing
`config/provisioning/zuribeans-{ug,za}.production.template.json` files
retain their **`draft-not-approved`** status and `REQUIRED_*` placeholders.
An **Accepted** design is *not* evidence of legal incorporation, approved
financial configuration, working intercompany accounting or permission
to operate in production.

**Numbering clarification:** ADR-ERP-023 (Baobab People) already has
**Accepted** status and is unaffected. This record accepts ADR-ERP-021,
the ZuriBeans two-market topology decision.
