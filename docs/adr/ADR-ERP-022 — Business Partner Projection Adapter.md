# ADR-ERP-022 — Business Partner Projection Adapter

**Status:** Accepted  
**Date:** 2026-09-20  
**Repository:** `baobab-platform/baobab-erp`  
**Related:** ADR-0023 (Trade, Proposed), ADR-ERP-005, ADR-ERP-007, ADR-ERP-014, Shared `contracts/erp/v1`

## Context

ZuriBeans buyer and supplier onboarding callers can mark `erp_projection_status=READY` when a
party is explicitly cleared for ERP projection (ADR-0012 in zuribeans). That readiness is **not** a Business
Partner. ADR-0023 requires:

```text
Canonical Organisation → Supplier Organisation → ExternalReference → C_BPartner
```

with ERP as the authority for committed vendor/accounting master data.

Shared `contracts/erp/v1` defines the public `business-partner-projection` payload and
forbids exposing iDempiere identifiers. The existing `IdempiereMasterDataBootstrapper`
already maps `MasterDataKind.BUSINESS_PARTNER` → `C_BPartner` with digest/version
reconciliation (ADR-ERP-014).

## Decision

1. Add `integration.business_partner_adapter.project_business_partner` as the only
   application-facing entry that turns a **readiness-gated** supplier (or customer)
   projection request into a native `C_BPartner` via the master-data bootstrapper.
2. Public `business_partner_id` is minted as `erp_` + opaque hex derived from the
   canonical organisation id and legal entity — never `C_BPartner_ID`.
3. Projection **fails closed** unless `readiness_status == "READY"`.
4. Native fields use AD_Column names (`Name`, `IsVendor`, `IsCustomer`, `IsActive`).
5. HTTP surface: `POST /business-partners/project` (workload scope `erp:integrate`),
   implemented via `application.business_partner_http.execute_project` and wired directly in
   `server.py`; documentation-only wiring is not an implementation.
6. iDempiere credentials remain optional; unconfigured AD_Client → HTTP 503.

## Estate handoff

```text
READY  →  POST /business-partners/project  →  PROJECTED
                │
                └ on error → estate marks FAILED
```

## Non-goals

- Estates or Trade calling iDempiere directly
- Bank account / payment master mutation (ADR-0023 §40–43)
- Automatic projection without readiness
- Returning vendor table IDs on the public API

## ZB-04 buyer projection

A verified Trade buyer relationship is projected with the `customer` role only after
`readiness_status=READY`. The request carries both identities without collapsing them:

- `canonical_organisation_id`: Control Plane canonical Party/organisation link.
- `source_customer_id`: Trade-owned buyer organisation identifier.
- `tenant_id` and `entity_id`: server-resolved ERP isolation scope.

The same canonical party may therefore have distinct C_BPartner representations and
distinct public `erp_*` identifiers in different legal entities. Replay is reconciled
by canonical identity, legal entity, source version and desired-state digest.
