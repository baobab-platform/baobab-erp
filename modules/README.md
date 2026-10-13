# Baobab ERP Application Services

Framework-free Python modules implementing the application layer between canonical
Baobab contracts and iDempiere, per ADR-ERP-005 through ADR-ERP-011. Nothing here
imports a web framework or any iDempiere-internal class; the only iDempiere-aware code
in this repository lives in `idempiere/extensions/`.

| Module | Responsibility | ADR |
|---|---|---|
| `context` | Resolve tenant/legal-entity headers into an `AD_Client`/`AD_Org` pair, failing closed | ADR-ERP-002, ADR-ERP-010 |
| `identity` | Carry an already-authenticated caller and its roles into the application layer | ADR-ERP-010 |
| `mapping` | Canonical entity ⇄ iDempiere native record resolution | ADR-ERP-007 |
| `events` | The signed canonical event envelope | ADR-ERP-006 |
| `security` | HMAC signing/verification for signed events | ADR-ERP-006, ADR-ERP-010 |
| `inbox` | Idempotent receipt of inbound events | ADR-ERP-006 |
| `outbox` | Transactional outbox recording and bounded-retry dispatch | ADR-ERP-006 |
| `integration` | The one seam that knows iDempiere's actual API shape, plus outbound webhook delivery | ADR-ERP-005 |
| `reconciliation` | Record-count (Layer 1) reconciliation; higher layers are tracked as open work | ADR-ERP-011 |
| `provisioning` | Legal-entity onboarding lifecycle state machine | ADR-ERP-019 |
| `application` | Thin orchestration (health checks today) | — |

## Design rule

Every module that needs persistent state defines a `Protocol` for its backing store
instead of importing a database driver directly. Tests exercise the logic against small
in-memory fakes (see `tests/unit/`); a Postgres-backed implementation of each store is
wired in `db/` once the schema in `db/migrations/` is applied, and is tracked in
`architecture/conformance.yaml` rather than silently assumed complete.

## Installing for development

```bash
cd modules
pip install -e .
```

## Testing

Unit tests for this layer live under `tests/unit/` at the repository root, not inside
`modules/`, so that `tests/` can also hold integration, contract, architecture,
tenancy, security, migration, and golden-transaction suites against the same layout
described in `docs/development.md`.

## P0-04A authority contract consumption

`shared_contracts` packages the exact pinned Shared schema closure and cached
format-enforcing validators. Legal/documentary PEPs, caller-context validation and
ERP assignments check wire facts before their separate semantic authority checks.
These validators and format dependencies are installed in production, with wheel
byte/inventory and isolated-runtime checks. See the
[maintenance plan](../docs/plans/P0-04A-erp-contract-convergence.md) for regeneration
and remaining protected acceptance requirements.
