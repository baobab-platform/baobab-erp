# Changelog

All notable changes follow Keep a Changelog and Semantic Versioning.

## [Unreleased]

### Security

- `idempiere/Dockerfile` swaps the Jackson 2.15.4 bundles in the pinned iDempiere
  image for 2.18.11 (CVE-2026-91776, CVE-2026-91777 in jackson-databind), as an
  ADR-ERP-004 section 5 emergency mitigation recorded in the Dockerfile with its
  owner, reason, removal condition and build guards. `jackson-datatype-joda` stays at
  2.15.4 because its 2.18 line needs joda-time 2.12 and the image ships 2.10.14.

### Added

- ERP serves the Finance baseline reference (Shared erp/v1 1.3.0, FB-02): `GET /legal-entities/{legal_entity_id}/effective-finance-baseline`
  and `GET /finance-baselines/{baseline_id}` (exact `version` and `digest`, never "the latest"), under `erp:provision` and a
  `TENANT_PROVISIONING` context. `POST /provisioning-operations` now requires `finance_baselines`, re-resolves each reference
  against ERP's own approved baselines and refuses with `FINANCE_BASELINE_MISMATCH` or `FINANCE_BASELINE_NOT_USABLE` (or
  `PLAN_AUTHORITY_MISMATCH` for disagreeing currencies) before provisioning anything. Finance can now withdraw its approval of a
  baseline version (append-only, migration `0017`); the command records the references it was accepted under. Re-pins Shared to
  `78b4e5e`.

### Changed

- Replaced the Frappe/ERPNext foundation-stage scaffold with an iDempiere-based
  foundation, per ADR-ERP-001 through ADR-ERP-020. No tenant, financial, or
  transactional data ever existed against the previous scaffold; see
  `docs/migration/erpnext-removal-report.md` for what was removed and why removal was
  safe now rather than deferred.
- Added `idempiere/extensions` (Baobab OSGi bundles), `modules/` (framework-free
  application-service layer), `db/migrations` (Baobab-owned Postgres schema),
  `migration/` (scaffolding for a future ERPNext-source migration), and
  `architecture/conformance.yaml` (an honest ADR conformance ledger).

## [0.1.0] - 2026-08-30

### Added

- Initial Frappe/ERPNext v16 engine foundation.
- Baobab custom app boundaries and mapping/event DocTypes.
- Bench, Docker Compose, Codespaces, CI, security, testing, and architecture documentation.
