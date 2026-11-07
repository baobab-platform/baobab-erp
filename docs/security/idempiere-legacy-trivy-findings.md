# Historical iDempiere third-party vulnerability scan exclusions — NOT ACTIVE

**BA-SEC-DEP-001 review date:** 2026-11-07. **Status: BLOCKED / REASSESSMENT REQUIRED.**

The former root `.trivyignore` contained 16 CVE exclusions without independent, per-finding, expiring Security approval. Its prose described upstream vendor libraries and an earlier review, but that does not satisfy the approved security-maintenance exception process. The active scan suppression has been removed. This archived file is NOT consumed by Trivy or a substitute for approval.

## Original exclusion list (historical only)

```text
# Vulnerability ignore list — vendor-bundled iDempiere dependencies
#
# Every ID below is a HIGH/CRITICAL finding inside a third-party Java library that
# ships pre-bundled as part of the pinned idempiereofficial/idempiere:13-release
# release artifact (its SourceForge-distributed server zip), not code this
# repository authors. Per ADR-ERP-004, Baobab does not fork or patch iDempiere core
# or its vendored plugin jars outside a dedicated ADR. Checked idempiereofficial/
# idempiere's full published tag list on 2026-09-06: 13-release is the only stable
# v13 build, so no newer image exists yet that resolves these.
#
# Review trigger: re-run this scan against each new idempiere/idempiere-docker
# 13-release build and drop entries once the base image's own dependency versions
# move past "Fixed Version" below. Tracked in architecture/conformance.yaml against
# ADR-ERP-013 (upgrades require compatibility tests).
#
# OS-level packages (e.g. openssl) are not listed here -- those are patched
# directly in idempiere/Dockerfile via `apt-get upgrade`, which doesn't touch
# iDempiere itself and needs no risk acceptance.

# jackson-databind -- fixed 2.18.8/2.21.4/3.1.4
CVE-2026-54512
CVE-2026-54513

# jackson-databind 2.15.4 (com.fasterxml.jackson.core.jackson-databind_2.15.4.jar)
# -- fixed 2.18.10/2.21.6/2.22.2. Added 2026-09-30: published after the
# 2026-09-06 review, same vendor-bundled jar as above.
CVE-2026-68497

# jasperreports -- fixed 7.0.4/7.0.7
CVE-2025-10492
CVE-2026-6009

# activemq-client -- fixed 5.19.4/6.2.4
CVE-2026-39304

# neethi -- fixed 3.2.2
CVE-2026-42402
CVE-2026-42403

# bouncycastle bcpg-jdk18on -- fixed 1.84
CVE-2026-3505

# bouncycastle bcprov-jdk18on (CRITICAL) -- fixed 1.80.2/1.81.1/1.84
CVE-2025-14813

# jetty ee8-jaspi/ee8-security/http/security/server -- fixed in 12.0.3x/12.1.x lines
CVE-2026-5795
CVE-2026-10050
CVE-2026-2332
CVE-2026-1605

# postgresql JDBC driver -- fixed 42.7.11/42.7.12
CVE-2026-42198
CVE-2026-54291

```

## Required independent triage

For each CVE above, review the current vendor advisory and **actual built iDempiere 13 image** after Baobab's versioned Bouncy Castle/Jackson interventions. Match the precise library jar, classpath, module, reachability and available fixed version rather than assuming the upstream base is still vulnerable. Record owner, exposure, fix/alternative, compensating control, expiry, review cadence and independent Security approval if an exception is unavoidable. Reconcile OSGi/native-finance/JDBC negative tests and CP/IAM posting authority before any deployment. Do not turn the historical file back on or treat the absence of a waiver as a passed scan.

Follow the [approved Shared policy v1.0](https://github.com/baobab-platform/shared/pull/429), Section 12. The historical approvals have not been independently verified; no protected release is authorized by this change.
