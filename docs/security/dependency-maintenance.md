# BA-SEC-DEP-001 — ERP dependency security-maintenance adoption

**Policy:** [Approved Shared v1.0](https://github.com/baobab-platform/shared/pull/429) — the approved document is authoritative; strict validator on Shared #429 is NOT yet merged or released.
**As reviewed:** 7 November 2026. **State:** SOURCE_COMMITTED; CI_VERIFIED, SECURITY_ALERT_PATH_VERIFIED, CONSUMER_QUALIFIED and protected-environment evidence are NOT YET VERIFIED.
**Owners:** Baobab ERP, Platform Engineering, independently reviewing Security. No implicit iDempiere release acceptance.

## Real inventory and Dependabot coverage

| Actual manifest | Ecosystem and location | Review boundary |
| --- | --- | --- |
| `.github/workflows/` | `github-actions` at `/` | Full SHA pinning and advisory provenance |
| Root `pyproject.toml` virtual uv workspace, `uv.lock`, `modules/pyproject.toml` | `uv` at `/` | Python PSYCOPG/JWT/authority validation, artifact lock and wheel qualification |
| `idempiere/extensions/pom.xml` OSGi reactor under root Maven aggregator | `maven` at `/idempiere/extensions` | OSGi/JVM native posting, JDBC, vendor compatibility |
| `idempiere/Dockerfile` iDempiere release-13 OSGi runtime | `docker` at `/idempiere` | Vendor image, override SHA, JVM native effects |
| `modules/Dockerfile` Python application-service image | `docker` at `/modules` | Installed packaged vs locked Python dependency parity |
| Root `compose.yaml` | `docker-compose` at `/` | Runtime PostgreSQL 17 and service topology |
| `idempiere/acceptance/erp-a/compose.yaml` | `docker-compose` at `/idempiere/acceptance/erp-a` | Disposable real CP/Ory/iDempiere/PG17 negative-test harness; NOT production |
| `.devcontainer/docker-compose.yml` | `docker-compose` at `/.devcontainer` | Reproducible developer tooling and test images |

No unsupported Node/npm entry was added; the root is Java/Python. Weekly maintenance is staggered Monday SAST. Only minor/patch version updates are grouped, with explicit `applies-to: version-updates`. Independent security fixes, Java/Python major changes and engine migrations are separately assessed. The redundant `target-branch: main` entries were removed: GitHub security updates target the default branch independently of nondefault version update options.

## P0 — Legacy CVE exceptions were not policy qualified

The prior root `.trivyignore` suppressed **16 CVE IDs** associated with an older iDempiere vendor runtime. It did not provide per-CVE independently approved scope, exact versions/reachability, owner, time-bounded expiry and remediation evidence. The active scanner bypass has been **deleted**; the complete source has been preserved as non-operative evidence at [legacy iDempiere findings](idempiere-legacy-trivy-findings.md).

This is intentionally **BLOCKED** for security acceptance, not a claimed clean scan or waiver. Current fixed Bouncy Castle/Jackson overrides in `idempiere/Dockerfile` could remove some original findings, but only scanning the actual assembled image and JVM classpath can confirm it. Validate against new vendor CVEs, JDBC, bundled OSGi jars, real JVM worker, CP/IAM authorisation, replay and Postgres 17. No automatic exemption may be reinstated. Follow Shared policy §12 for independent, expiring exceptions where no remediation is feasible.

The root `CODEOWNERS` referenced `@nabhold/` teams despite this repository being in `baobab-platform`; it now uses Baobab Platform Engineering/Security review paths. Actual team resolution and branch protection still need GitHub readback.

## Daily advisory surveillance / current limitations

The existing `.github/workflows/security.yml` now schedules a **daily** disposable Python lockfile security check: pinned `uv==0.13.7` exports the **full workspace** from committed `uv.lock` (`--frozen --all-packages --all-extras --no-emit-workspace`), fails on an empty export and passes exact pinned third-party packages to `pip-audit==2.10.1 --strict --no-deps`. No unbounded `--ignore-vuln` or scanner-error-as-green behavior is introduced. Existing CodeQL/secrets workflow remains.

**Java-native advisory adapter is not yet verified.** The Foundation/native Trivy image and Maven/OSGi CI checks remain essential but are not a substitute for a proven Maven vulnerability adapter or native iDempiere runtime/assembled-image scan. This limitation remains an explicit security closure blocker; no Java-native PASS is claimed.

**Further supplier-chain issue to resolve before protected rollout:** `modules/Dockerfile` installs editable Python source with resolver-selected versions via `pip install -e .` rather than demonstrably installing the exact `uv.lock` resolution. The Python update config and daily lockfile scan alone do not prove deployed wheel dependency parity. Resolve with a separate owner-qualified runtime image change and independent readback. Image builder tags (e.g. `maven:3-eclipse-temurin-27`) likewise require actual immutable digest/provenance receipts.

## Validation, evidence and next actions

1. Run `python3 -m unittest discover -s tests/unit -p 'test_dependency_maintenance.py' -v` in the pinned PyYAML verifier; verify accepted pinned Shared baseline with all five applicable ecosystems. Do not invoke the unmerged Shared #429 strict validator in protected CI.
2. Independently verify Dependabot GitHub settings, version jobs, security alerts, automatic security updates, Actions SHA advisories, uv workspace and Maven multi-module update behavior. GitHub supports `uv` as an ecosystem; working security alerts require actual inventory/readback.
3. Run the daily lockfile audit; execute the existing native PostgreSQL17/JVM finance integration, restored inbox/replay, Security, Foundation and OSGi/Java test matrices at the **actual final head**. Record actual results, not inferred pass.
4. Remediate/triage each historical and new High/Critical finding using the approved policy deadlines; no waiver can be self-certified or indefinite.
5. Only then consider CI_VERIFIED, SECURITY_ALERT_PATH_VERIFIED and CONSUMER_QUALIFIED. Staging and production remain independently approval-protected.

**No merge, CI execution, production qualification or native financial authority acceptance is claimed by this source change.**


## 12 November 2026 — independently observed JasperReports security blocker

**Actual evidence:** Foundation run [43162173694](https://github.com/baobab-platform/baobab-erp/actions/runs/43162173694), native-image job 130995691684, independently rebuilt the candidate `idempiere/Dockerfile` image and ran Trivy 0.73.0 against the full Ubuntu Noble/Java package inventory. The strict validator refused:

- CVE: **CVE-2025-10492**; package: `net.sf.jasperreports:jasperreports`;
- actual installed version **6.21.0**; scanner-reported patched version **7.0.4**; severity **HIGH**;
- result: **VENDOR_VEX_OTHER_HIGH_CRITICAL_FINDING**; Foundation is **red**.

This is distinct from the separately adjudicated Ubuntu Noble `apt` vendor-patched advisory. It is **not** an allowed USN-8996-1 match and is not covered by any approved exception. The bounded diagnostic now gives the real advisory/package identity without exposing arbitrary scanner payloads.

**Independent upstream reference:** [GitHub Security Advisory GHSA-7c3f-cg9x-f3gr](https://github.com/advisories/GHSA-7c3f-cg9x-f3gr) describes a deserialisation/code-execution risk in JasperReports below 7.0.4. [Jaspersoft's October 2025 FAQ, updated March 2026](https://community.jaspersoft.com/knowledgebase/faq/update-details-about-the-java-vulnerability-r4897/) explicitly says the Community fix is **not backported to 6.x**. Thus there is no basis to claim that a patch-level bump within 6.21 can remediate this finding.

**Required engineering decision, not an automatic dependency bump:** audit iDempiere 13's OSGi JasperReports bundle, its compiled `.jasper` report compatibility, class-space wiring, custom report rendering, JRXML/report compilation, export behaviour and upstream build contracts before proposing a 7.0.4+ migration. Removing the jar or simply replacing a 6.x jar with 7.x may break native reporting and is not a qualified patch. No reporting input should be assumed trusted without a documented, exercised boundary. A compensating restriction or time-limited scoped exception requires independent Security evidence and approval; it must never be silently encoded into `.trivyignore` or `--ignore-unfixed`.

**Next acceptance:** produce a bounded JasperReports version remediation PR with actual OSGi/container classpath readback, report fixtures, native ERP Gate D/ERP-A and all negative tests, then rerun unrestricted full-image Trivy. Keep ERP #131 **DRAFT/HOLD** until that gate is green or independently approved expiring vulnerability disposition exists. This source note alone does not close the vulnerability.
