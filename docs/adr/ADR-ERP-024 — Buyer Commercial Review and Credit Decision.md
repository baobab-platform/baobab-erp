# ADR-ERP-024 — Buyer Commercial Review and Credit Decision

**Status:** Accepted  
**Date:** 2026-09-20  
**Related:** ADR-ERP-006, ADR-ERP-008, ADR-ERP-014, ADR-ERP-023; Trade ADR-0017 and ADR-0027

## Decision

ERP is authoritative for the buyer's accounting credit status, credit limit and payment terms.
A workload-authenticated, legal-entity-scoped decision command records immutable audit evidence
and a transactional outbox event using
`com.baobab-platform.customer.buyer-commercial-profile.changed.v1`.

An approved profile must name payment terms. Prepayment-only approval is represented explicitly
with `payment_term_code=PREPAYMENT` and a zero credit limit; it is not a bypass around review.
`ON_HOLD` and `REJECTED` never activate Trade purchasing.

The decision preserves tenant, legal entity, Trade buyer organisation, canonical organisation,
ERP public Business Partner, reviewer Principal, decision reference, profile reference and
idempotency evidence. Native iDempiere identifiers are never published.

## Consequences

Trade may activate a PENDING buyer only from an ERP-sourced APPROVED commercial profile whose
tenant, legal entity and buyer identity match the pending relationship. Duplicate commands are
replayed; an idempotency-key payload mismatch fails closed.
