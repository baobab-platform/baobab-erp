# ADR-ERP-023 — Buyer Projection Event Consumer

**Status:** Accepted  
**Date:** 2026-09-20  
**Related:** ADR-ERP-006, ADR-ERP-007, ADR-ERP-010, ADR-ERP-014, ADR-ERP-021, ADR-ERP-022

## Context

A buyer registration event scoped only to a tenant cannot select an ERP legal entity. ZuriBeans
operates independent Uganda and South Africa legal-entity contexts, and ADR-ERP-021 forbids
silently collapsing them into one AD_Client/AD_Org representation.

## Decision

ERP consumes an explicit signed
`com.baobab-platform.customer.buyer-erp-projection.requested.v1` event. The envelope must carry
both `tenantid` and `entityid`; the data carries the separate Trade buyer organisation and
Control Plane canonical organisation identifiers.

The consumer:

1. verifies and records the signed event through the existing ADR-ERP-006 inbox;
2. resolves tenant/legal-entity mapping server-side;
3. uses the configured iDempiere client for that AD_Client;
4. projects the Party as a customer through ADR-ERP-022;
5. records processed or failed inbox state;
6. safely reprocesses delivery retries using the existing digest/source-version mapping.

A generic buyer registration event is not sufficient authority to choose a legal entity.

## Consequences

- No estate or Trade process writes iDempiere tables directly.
- Uganda and South Africa projections remain independently addressable.
- Missing mapping, credentials, scope or required payload fails closed and remains retryable.
- This event creates a Business Partner representation only. Credit and payment terms remain
  separate ERP-owned decisions.
