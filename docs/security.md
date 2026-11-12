# Security

See `SECURITY.md` at the repository root for the vulnerability-reporting policy. This
page covers the security architecture referenced there (ADR-ERP-010).

## Chain

```text
Identity
   ↓
Authentication (Baobab IAM; workload callers verified in this repository -- see below;
                human iDempiere WebUI login is iDempiere's own built-in OIDC plugin,
                configured per docs/sso-configuration.md)
   ↓
Trusted Principal (modules/identity.ServiceIdentity)
   ↓
Baobab Context (modules/context, fails closed)
   ↓
Capability Authorization (Control Plane CapabilityBinding)
   ↓
Canonical Mapping (modules/mapping, fails closed)
   ↓
iDempiere native authorization (AD_Role / AD_Client / AD_Org)
```

## Fail-closed rules

- `modules/context.resolve_context` raises `ContextResolutionError` on a missing,
  incomplete, or unresolved tenant/entity pair. It never falls back to a default tenant.
- `modules/mapping.resolve_to_native` / `resolve_to_canonical` raise
  `MappingNotFoundError` rather than guessing by display name or lazily creating a native
  record.
- `modules/inbox.receive` rejects an inbound event whose signature does not verify
  (`InvalidSignatureError`) before the envelope is even parsed for business fields.
- `security.workload_auth.verify_workload_token` (Gate IAM-10, ADR-0014 §111) rejects
  any `/context/resolve*`/`/mapping/resolve*` request with a missing, malformed,
  wrong-issuer, wrong-audience, expired, or non-`workload`-actor bearer token before
  either surface runs at all -- `application/server.py` maps every rejection reason to
  the same 401, so a caller can't use the response to calibrate a forged token.
- Gate ZB-03.8: authentication alone isn't authorization. Each of those same four
  endpoints also requires its token's `scope` claim to grant the specific scope that
  endpoint needs (`application/server.py`'s `_WORKLOAD_REQUIRED_SCOPES`,
  `ServiceIdentity.has_role`) -- a validly authenticated workload token that lacks it
  gets `403`, kept distinct from the `401` an unauthenticated caller gets. Every
  endpoint currently requires `erp:integrate`, the only scope granted to any workload
  client today (`baobab-iam/config/scopes/erp-integrate.json`); splitting per-resource
  scopes is a follow-on once a real client needs less than full access.

## Cross-tenant access

A resolved context for one tenant must never satisfy a request scoped to another; this is
tested explicitly in `tests/tenancy/test_context_resolver.py`
(`test_cross_tenant_pair_fails_closed`). A cross-tenant access attempt is a security event
requiring audit retention, not merely a denied request.

## 5 November 2026 — Ubuntu Noble patched APT / Trivy advisory lag

ERP PR #125's exact-head Foundation container run `41985870878` built the
real iDempiere 13 image and then failed Trivy 0.73.0 on two HIGH findings
for `CVE-2026-109518`: `apt` and `libapt-pkg6.0t64`, installed
`2.8.4ubuntu0.1` (no fixed version known to the then-downloaded Trivy DB).
This is **not** a finding against the separately upgraded ActiveMQ 5.19.12,
which was scanned with zero issues.

The upstream source of truth is Canonical's USN-8996-1,
<https://ubuntu.com/security/notices/USN-8996-1>, and Ubuntu's published
CVE record, <https://ubuntu.com/security/CVE-2026-109518>. Both identify
**`2.8.4ubuntu0.1` as the actual released fixed version for Ubuntu Noble
24.04** on 4 November 2026. The existing ERP Dockerfile patches APT before
other unguarded package operations and asserts both installed versions
against that security floor; disabling APT retries prior to the patch is
preserved. No image package is downgraded or forcibly removed.

**Independent, mandatory verification:** the ERP Foundation workflow first
runs its own `vendor-patch-audit` job against a freshly rebuilt **same
actual final Dockerfile**. It obtains APT package versions directly from
an offline, network-isolated, read-only container using `dpkg-query`,
executes an unfiltered Trivy HIGH/CRITICAL JSON scan, and calls
`scripts/check_ubuntu_vendor_cve.py`. That verifier requires precisely
Ubuntu Noble and **both exact patched APT package versions**; it refuses
every other HIGH or CRITICAL finding including any new/unfixed CVE, wrong
package, earlier version, duplicate or malformed evidence. Negative tests
run inside that job. If it fails, the normal reusable Foundation job is
not eligible to run. This prevents a broad `--ignore-unfixed` false
success on newly discovered issues.

Only **after** that unfiltered, independently validated scan succeeds,
the pinned reusable Foundation scan uses its existing opt-in
`container_ignore_unfixed` input to avoid *double-counting* the
Trivy-database-lag false positive. All fixed-version CVEs, ordinary
policy, SBOM and other Foundation gates still apply. The gate does not
waive an actually vulnerable version, exempt any additional finding or
certify protected release. If the original Trivy DB is corrected, remove
the opt-in and second scan together after final-head requalification.

This is a **vendor-adjudicated scanner finding, not a synthetic security
PASS**. Its first live GitHub Actions run must still pass, and the DEV-11
same-event native JVM, CP lineage, replay and exported trace requirements
remain distinct; all L4-OPS-01 and production admissions stay BLOCKED.
