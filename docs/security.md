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
