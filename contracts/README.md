# Baobab ERP Interface Contracts

`baobab-platform/shared` is canonical for every contract ERP implements or consumes (see `contracts.lock.yaml`
for the pinned commit). ERP keeps no schema of its own for events: the envelope is
`contracts/events/v1/envelope.schema.json` in Shared and the registered event types are indexed in
`modules/events/registry.py`.

Payload schemas must never contain database table names or require another engine to understand iDempiere internals.
