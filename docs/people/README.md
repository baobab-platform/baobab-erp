# Baobab People — ADR-ERP-023 BP-00/BP-04 engineering

**Status: experimental adapter implementation; accepted Shared capability vocabulary exists, but no live certified HR/payroll provider, statutory qualification or native GL integration.**

Governing decision: accepted ERP ADR-ERP-023. Shared PR #434 is merged as Accepted ADR-SHARED-045, registering four DRAFT/EXPERIMENTAL People v1 capabilities. Canonical semantics do not mean provider runtime acceptance. Java 17 + iDempiere 13 + PostgreSQL 17 are the **current deployable baseline**. Java 21 remains a target only until independently qualified in the actual OSGi runtime.

## What can execute in the current BP-04 candidate

- `workforce/`: employer-scoped version proposals, IAM/CP attested writer, effective history and PostgreSQL 17 atomic compare-and-append.
- `payroll/`: employer/run-scoped draft metadata with maker identity, immutable period/jurisdiction/currency, revision/correction lineage, pinned (but **not certified**) rule-pack digest and atomic versioning. Calculation eligibility still requires an independently qualified signed provider receipt and separate checker. Draft persistence confers **no approval**.
- `db/people-migrations/P0001–P0002`: PostgreSQL schema/guards for **opaque** references only. Employer/tenant is the isolation key, independent of iDempiere client IDs. Triggers refuse UPDATE, DELETE, TRUNCATE, concurrent/stale versions, crossover corrections and changed payroll period. Native iDempiere finance and payment tables remain untouched.
- `modules/people/*/postgres_store.py`: parameterised persistence ports. Callers own transactions and must supply a separately verified current IAM/CP authority adapter. They do **not** establish authority by themselves.
- `tests/integration/test_people_postgres.py`: disposable PostgreSQL 17 readback and negative tests, run in CI with explicit opt-in.

## Permanent tenant choice (8 November directive)

**Bring Your Own Provider (BYOP)** is a first-class product requirement across HRIS/workforce, attendance, leave and payroll, not a fallback limited to payroll bureaus. The legal employer chooses the authority for each function and effective period; Shared defines the provider-neutral contract and CP governs any Baobab-side provider binding, subject to IAM, jurisdiction and evidence. No provider is allowed to silently replace, double-write, re-finalise or export restricted employee records merely because Baobab People is installed.

See [Provider-neutrality and portability design](provider-neutrality.md) and ADR-ERP-023 Addendum B for the source-of-record matrix, mixed-provider design, migration-out and BYOP-01…12 acceptance cases. **This PR now includes a guarded provider-selection and signed external payroll-evidence adapter port** (see [provider adapters](provider-adapters.md)). Those are not live qualified providers or activated CP bindings: current CP #466 and IAM #157 remain gated; no vendor issued a verified runtime receipt in this PR.

## Accepted Shared contract and BYOP adapter increment (8 November 2026)

The stable canonical interface is [Shared ADR-SHARED-045](https://github.com/baobab-platform/shared/pull/434). Shared #436 proposes the non-authorising `people:provider:read` workload scope. CP #466 and IAM #157 provide independently gated development-only provider-selection enforcement.

The new `people.providers.selection.CPProviderSelector` accepts only trusted `context_id`, one of the four accepted capability names, correlation and major version. It rejects untrusted provider/employer selection and verifies CP readback freshness and jurisdiction. `people.providers.evidence.ExternalEvidenceAdapter` verifies an Ed25519-signed source-payroll evidence receipt bound to that chosen provider, employer, run/version, jurisdiction, rule digest and binding revision. `SelectedCalculationVerifier` implements the existing PayrollEligibilityGate verifier port, but also demands a **separate independent statutory reviewer signature**. The qualification reader has **no defaults or keys**, so all real calls deny until authorised evidence custody is provided.

The native PG17 draft scaffold remains **draft-only** and cannot be used as a qualified native payroll calculator. External-only and hybrid BYOP arrangements do not need to post iDempiere or run Baobab Payments. The new synthetic signature tests are not legal or statutory certification.

## Disabled by default

`db/migrate.sh` and Docker production entrypoints **do not run** People schema migrations. To install into a **throwaway** PG17 ERP application database only after `db/migrate.sh`:

```bash
BAOBAB_ENVIRONMENT=integration BAOBAB_PEOPLE_EXPERIMENTAL=1 \
  bash db/migrate-people-experimental.sh
BAOBAB_PEOPLE_EXPERIMENTAL=1 BAOBAB_PEOPLE_TEST_DISPOSABLE=1 \
  PYTHONPATH=modules python3 -m unittest discover -s tests/integration -p 'test_people_postgres.py' -v
```

Never run these against a persistent employee-bearing database. The experimental tables are append-only and tests deliberately leave synthetic evidence in the disposable CI database. They contain no employee names, national/tax IDs, compensation, benefits, bank details, payslips or statutory rates.

Current guards **do not implement production database-level tenant roles/RLS, accepted Shared People contracts, genuine CP credentials or installed iDempiere People OSGi bundles**. Dedicated native extension/2Pack work must follow a proven extension point and the approved schema. Do not advertise implementation status in the capability catalogue.

## BP-01/02/03/05/06/07 still open

- CDSoftware release/commit, GPLv2 licence/dependencies, source provenance and corresponding-source obligations must be reviewed independently before code is copied. No vendor code has been imported. Native plugin compatibility with 13 is unproven.
- For an actual employer: current IAM/CP legal scope, HR data protection and employer payroll registrations, private mappings and approved evidence custody.
- ZA statutory pack requires expert-approved PAYE/UIF/SDL/ETI, tax-year/registration details, signed vectors and supervised parallel payroll. UG URA/NSSF comes later, separately. No rate is hardcoded.
- A qualified external payroll provider remains the first-pay contingency for Nabhold **and a permanent tenant choice for all customers**, not a forced migration staging state. Any tenant can keep existing HR, attendance, leave, payroll or filing providers indefinitely, or combine independently qualified native and external functions; no native Baobab People, iDempiere journal or Baobab Payments activation is required merely to use another Baobab capability. Payroll calculation, approval, native journals (where requested), liability reconciliation, payment release (where requested), filing, legal retention, multi-company proof and EA-09 activation are independently gated.
- No employment proposal or payroll draft stored here is proof that the person is employed or money is owed.
