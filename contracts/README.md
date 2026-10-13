# Baobab ERP Interface Contracts

`baobab-platform/shared` is canonical for every contract ERP implements or consumes (see `contracts.lock.yaml`
for the pinned commit). ERP keeps no schema of its own for events: the envelope is
`contracts/events/v1/envelope.schema.json` in Shared and the registered event types are indexed in
`modules/events/registry.py`.

Payload schemas must never contain database table names or require another engine to understand iDempiere internals.

## P0-04A implementation (13 October 2026)

The immutable lock now declares the actual legal-actor, documentary, context and
assignment consumers and their reference closure. Generated files in Python and
JVM resources preserve original Shared bytes with hash/entry-point provenance;
they are consumed artifacts, not locally owned canonical definitions. See the
[regeneration and compatibility plan](../docs/plans/P0-04A-erp-contract-convergence.md).
