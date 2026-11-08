# Baobab People runtime target and qualification matrix — 2026-11-07

| Dimension | Target | Current evidence / remaining gate |
| --- | --- | --- |
| iDempiere | Orion 13 | Existing pinned runtime; do not fork core |
| Java **21** | Target for first-party People and eventually ERP runtime | DEV10-R3 Java 21 compilation/bytecode probe and native finance PG17 tests exist; real iDempiere 13 runtime on Java 21 is **not yet qualified** |
| PostgreSQL **17** | Required | Already the configured image/CI baseline; existing PG16 physical volumes require separately supervised migration |
| CDSoftware | Optional reference/adapter | No release/license transitive dependency or Payroll-on-13 compatibility certified; no vendored source |
| Tenant's existing HRIS/payroll vendor (BYOP) | Optional, permanent first-class choice | Per-employer/function/jurisdiction adapter + CP binding; no provider qualified or bound yet, no forced native People/ERP/Payments migration |
| ZA payroll | First | No legal/statutory golden vectors certified, no live provider |
| UG payroll | Second | No legal/statutory qualification certified |
| Payroll GL | ERP-owned | Use existing independent native posting/mandate veto; not connected to People |
| Payroll money movement | Separate Payments/Treasury | Never implied by run approval |

Decision: move toward JDK21 deliberately, but never relabel a Java17 production image as qualified Java21. First-party People source can use Java21 only behind a non-deployable compatibility gate until actual iDempiere 13/Equinox/OSGi, payroll provider, security and tenant/financial-negative testing succeeds. The effective runtime release requires a separate reviewed change. PostgreSQL17 is already the baseline, not an automatic upgrade of existing storage.

Source references: `docs/assessments/dev10-r3-java21-compatibility.md`, `.github/workflows/dev10-r3-java21.yml`, `upstream.lock.yaml`, iDempiere release-13 development prerequisites.
