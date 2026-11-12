# CDSoftware candidate audit — ADR-ERP-023 BP-01, non-adoption

**Decision: HOLD / independently develop the BP-04 metadata boundary. No CDSoftware code or 2Pack incorporated.**

| Candidate | Public upstream evidence | Audited claim / decision |
| --- | --- | --- |
| CDSoftware Payroll | iDempiere wiki Plugin: CDSoftware Payroll | Page documents tested release **10.0.0**, GPLv2 and dependencies CDSoftware Base / Globalqss DetailNames. No reproducible iDempiere 13 compatibility proof. HOLD. |
| CDSoftware Base | iDempiere wiki Plugin: CDSoftware Base | Page documents tested release **12.0.0** and GPLv2. This does not qualify Payroll 13. HOLD. |
| First-party Baobab People | ERP ADR-ERP-023 / PR #126 | Independently authored non-PII metadata + version/authority ports. No upstream source copied. Candidate for qualified contract and native extension later. |

Source references (informational, not immutable provenance):
- https://wiki.idempiere.org/en/Plugin:CDSoftware_Payroll
- https://wiki.idempiere.org/en/Plugin:CDSoftware_Base
- https://docs.idempiere.org/docs/basic-installation/installing-for-development/manual-install/install-development-prerequisites

**Open BP-01 evidence required:** exact upstream Git commit/tag and distribution URL, license and attribution audit, compatible dependency tree and 2Pack/OSGi metadata, build reproducibility, security scan/SBOM, license counsel for commercial distribution, maintainers' support statement, and Java 17/iDempiere 13/PostgreSQL 17 runtime test. None is claimed. An unverified Payroll 13 port or Java 21 certification must not be inferred from this register.

**Target component decisions:** workforce metadata/version control = independently develop; statutory payroll engine = provider-first pending ZA pack; payroll GL = reuse ERP native posting veto through an accepted contract; employee documents = reuse governed ERP evidence custody. Revisitable when verified candidate source/compatibility evidence exists.
