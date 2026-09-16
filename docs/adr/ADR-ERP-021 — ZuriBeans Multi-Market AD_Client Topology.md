# ADR-ERP-021 — ZuriBeans Multi-Market AD_Client Topology

**Status:** Proposed  
**Decision class:** ERP / Tenancy / Canonical Mapping / Organisation Model  
**Scope:** `nabhold/baobab-erp`, `nabhold/baobab-cp`, `nabhold/zuribeans`  
**Parent ADR:** ADR-ERP-002 — ERP Tenant, Client and Organization Mapping  
**Related:** ADR-ERP-008 — ERP Financial, Accounting and Multi-Currency Architecture; ADR-ERP-019 — ERP Provisioning, Tenant and Legal-Entity Onboarding, Migration and Decommissioning Architecture; `zuribeans/docs/adr/ZuriBeans Go-Live Implementation Plan` Gate ZB-16  
**Date:** 2026-09-16

---

# 1. Decision

ZuriBeans operates in two markets — Uganda and South Africa — and ADR-ERP-002 §28 and ADR-ERP-008 §179
both explicitly forbid inferring a multi-market tenant's `AD_Client`/`AD_Org` topology from country codes
or defaulting it. This ADR records that choice for ZuriBeans.

ZuriBeans SHALL be represented as **two separate iDempiere `AD_Client`s**, one per country:

```text
ZURIBEANS_UG   — ZuriBeans Uganda,      LegalEntity: zuribeans-ug
ZURIBEANS_ZA   — ZuriBeans South Africa, LegalEntity: zuribeans-za
```

This is ADR-ERP-002 §28's "Pattern B" (as opposed to Pattern A: a single `AD_Client` with markets
represented as `AD_Org`s or accounting dimensions). Both `AD_Client`s SHALL share the existing
`ERP-AF-SOUTH-01` `EngineInstance` alongside `NABHOLD` and `THAMANI`'s own Clients, per ADR-ERP-002 §131's
default shared-instance topology and ADR-ERP-019 §27/§242's sanctioned rollout order — this is an
operational choice (fewer EngineInstances to operate), not an architectural requirement to isolate further;
a dedicated `EngineInstance` per Client remains available later if residency or isolation requirements
change (ADR-ERP-002 §13).

Each `AD_Client` gets its own `LegalEntity`, its own `CapabilityBinding`, and its own accounting
configuration (functional currency, chart of accounts, fiscal calendar, tax profile) resolved independently
per ADR-ERP-008 §19/§177 — never shared or defaulted from the other market.

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

Choosing two `AD_Client`s makes ZuriBeans UG ↔ ZuriBeans ZA an **intercompany** relationship the moment both
markets transact with each other (the masterplan's Gate ZB-11, "Internal Cross-Market Trade," and its
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

- ZuriBeans Uganda and ZuriBeans South Africa are treated as independently registered legal entities for
  statutory reporting purposes (separate jurisdiction codes, separate functional currencies — UGX vs ZAR —
  separate tax profiles), which ADR-ERP-008 §19 ties to the `LegalEntity` level, not the `AD_Org` level.
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
  calendar and tax profile SHALL be configured and approved independently; neither is copied or defaulted
  from the other.
- **INV-ERP-TOPO-004** — Both Clients SHALL resolve to the same `EngineInstance` (`ERP-AF-SOUTH-01`) unless
  a future ADR records a residency or isolation requirement that necessitates separating them, per
  ADR-ERP-002 §13's isolation escalation path.
- **INV-ERP-TOPO-005** — The ZuriBeans provisioning configuration SHALL be two independent
  `ErpProvisioningRequest` documents (one per Client), never a single request carrying two `markets` entries
  under one `legal_entity_id`.

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
