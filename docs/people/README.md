# Baobab People — BP-00/BP-04 foundation

Governing decision: **ADR-ERP-023** (ERP-local); contract obligations: Shared PR #434, `proposals/people-contracts/` (not yet accepted).

## What is implemented

- `modules/people/workforce/`: immutable, effective-dated employer-specific workforce version proposal, with two independent boundary ports (current IAM/CP authority and atomic compare-and-append repository).
- `modules/people/payroll/`: restricted payroll draft and independently verified calculation/approver *eligibility* check. The gate rejects cross-employer, cross-tenant, stale, incomplete, unqualified, wrong currency/pack and self-approval cases.
- Explicit seams for providers, country localisation and reconciliation; unit negatives under `tests/unit/test_people_scaffold.py`.
- `planned_capabilities` in the ERP provider declaration. They are **not canonical or supported**, and cannot be resolved, bound or activated.

These are non-persistent, pure application-domain and policy components. There is intentionally no DB migration, actual worker, HTTP route or OSGi People bundle: the domain does not yet have an accepted Shared schema or trusted CP integration, and adding a production data pathway now would falsely establish authority.

## Before first real HR transaction or pay run

1. Shared approves an explicit, versioned workforce/payroll contract and namespace; ERP pins it.
2. IAM/CP provide *real*, current employer/actor/mandate authority; employee identity alone grants nothing.
3. Implement transactional repository adapters and protected query/mutation boundaries; prove employer isolation, effective history, idempotency, concurrency and lawful-purpose audit.
4. Independently qualify a payroll provider, ZA rule pack, signed statutory golden vectors, proof of filing/registrations and supervised parallel pays; then UG separately.
5. Connect approved payroll aggregate journal to existing native iDempiere posting veto. Money movement requires separate Payments/Treasury approval, never a People call.
6. Qualify Java 21 in a genuine iDempiere 13 OSGi runtime with PostgreSQL 17, negative posting tests, independent readback, supply-chain/security checks and rollback. Until then, Java 21 remains the **target** and the current Java 17 deployment remains unchanged.

Run: `PYTHONPATH=modules python3 -m unittest discover -s tests/unit -p 'test_people_scaffold.py' -v`

No real employee records, payslips, statutory rates, CDSoftware code or fake success data ship with this increment.
