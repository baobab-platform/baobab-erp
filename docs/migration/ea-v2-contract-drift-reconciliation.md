# EA v2 contract reconciliation — 2026-10-04

Target: Shared main `43135a80fd2a1b6b05060edd39bea9abb0823903` (first `6899a2d8f143bf23d36c4f4ac904e0a1e10c3cea`; see the addendum).

The consumed ERP OpenAPI changes from 1.0.5 to 1.1.0. Provisioning command/state,
order-consequence and inventory reads now take required caller-bound CP context
authority. Mapping reads continue to use the authenticated token's tenant claim.
The provisioning request adds required `context_id`; approved-plan tuple and
Finance-baseline checks remain independent requirements.

ERP validates context through `POST /v1/platform-context/validate` with the actual
incoming bearer as `subject_token` and a separate ERP validator bearer. It never
asserts a caller issuer/subject or derives tenant authority from body, query,
provider metadata or an unvalidated context. Validation precedes database access,
including replay reads. Missing/malformed context is 400; all CP authority
refusals and tenant disagreements are indistinguishable 403
`ERP_CONTEXT_REJECTED`; unavailable or malformed CP responses are retryable 503.
Successful validation requires the requested context, canonical tenant and bounded
current expiry. No legal-entity authority is inferred from this response.

`context_id` is authorization evidence, excluded from the provisioning fingerprint.
A fresh valid context for the same caller and request replays the original operation.
It cannot substitute for the exact approved plan id/version/digest or Finance baseline.

Deployment wiring is optional at startup and fails closed on the four protected
operations when absent. Both `ERP_CONTEXT_VALIDATION_URL` (trusted CP base URL) and
`ERP_CONTEXT_VALIDATION_TOKEN_FILE` must be configured together. The file must contain
an externally issued, short-lived ERP access token for CP, not a projected assertion
or a static client secret; it is reread for each validation so managed rotation is
visible. Token and subject are never logged or included in errors; redirects are
refused and response size/time are bounded.

This PR creates no validator registration, `context:validate` grant, workload
activation or deployment. Production access remains blocked until Shared registry
governance, IAM issuance and CP's registered `validates_audiences` relation authorize
ERP as a validator for its resource audience. CP remains authority for that decision.
Existing assignment-read credentials and `erp-assignment:read` are not reused or expanded.

Evidence: stdlib validation tests; real HTTP rejection-before-storage tests;
Postgres handler replay with fresh contexts; and exact-pin Shared schema/OpenAPI
conformance. Mock CP answers establish engine behavior only, not deployed validation
or workload activation evidence. The repository and Foundation CI gates must pass
at the reviewed PR head before merge.

## Addendum — 2026-10-07: reconciled with the merged caller matrix (Shared 43135a8)

Shared #235/#236 and baobab-iam #81 have merged since this reconciliation was written. What changes for ERP:

- **Pin.** `43135a8` carries erp/v1 **1.1.1**: `GET /provisioning-operations/{operation_id}` requires `erp:provision`, not
  `erp:read`. Following a provisioning operation is part of provisioning, so the identity that submits one never needs
  `erp:read`, which is reserved for the business-data reads (mappings, order consequences, inventory availability). The
  scope is checked before the Control Plane is asked, so a caller without it causes no validation call.
- **Registered validator.** `baobab-erp-workload` is now the registered validator of the `baobab-erp` audience in the Shared
  workload registry (`context:validate`, `validates_audiences: ["baobab-erp"]`), and baobab-iam issues `context:validate`
  (audience `baobab-control-plane`) to it. It no longer holds `erp:read` or `erp:provision`: ERP is the resource server of the
  Boundary API, not a caller of it. The validator token file configured above is therefore that client's token requested with
  `scope=context:validate`; it must not be shared with any caller. Allocation is not activation: nothing is promoted to
  `ACTIVE` here, and deployed validation is still unproven.
- **Callers.** `baobab-trade-workload` is allowed `erp:read` (an optional scope, so its default tokens stay Control-Plane-only);
  the Control Plane's provisioning worker, `baobab-cp-provisioning-workload`, is `PROVISIONED` with `erp:provision` only. Each
  caller resolves its own context, so the context's owner is the caller's canonical principal, and ERP forwards that caller's
  own bearer as `subject_token`, never its own validator token.
- **What a Control Plane refusal means.** Only what the Control Plane says about the caller is a rejection (403
  `ERP_CONTEXT_REJECTED`): `SUBJECT_TOKEN_INVALID` (401), `CONTEXT_NOT_FOUND` (404), `TENANT_CONTEXT_MISMATCH` and
  `TENANT_NOT_ACTIVE` (403), `VALIDATION_FAILED` (400), each only with its own status. Anything else, in particular a 401 for
  ERP's own validator token or a 403 for an unregistered validator, is ERP's configuration or an outage and stays a retryable
  503; reporting it as a rejected context would blame every caller for ERP's misconfiguration.
- **503.** Every 503 on these operations, including an unconfigured validator, carries an integer `Retry-After`, as the contract's
  ServiceUnavailable response requires.

Still open, unchanged: mapping reads take their tenant from the token claim, and the tenant-neutral caller tokens issued under
the new matrix carry none, so those reads are unavailable to them until that is decided separately.

## Addendum — 2026-10-07: pre-activation provisioning context (Shared 05db746)

The Control Plane activates a tenant only after provider provisioning, so the context that authorises ERP provisioning
cannot be one that requires an ACTIVE tenant (ADR-ERP-019 section 6; Control Plane ADR-BCP-017 sections 22 and 45). Shared
control-plane/v1 **1.34.0** and erp/v1 **1.2.0** (`docs/architecture/context-authority-for-workloads.md` section 13) add an explicit
**authority purpose** to every validated context instead of relaxing the ACTIVE rule. What changes for ERP:

- **Pin.** `05db746`. The Control Plane's validation answer now always states `authority_purpose` (`RUNTIME` or
  `TENANT_PROVISIONING`), and `provisioning_authority` (the approved plan's provisioning id, plan id, version and digest)
  exactly for the latter. ERP parses both strictly: an answer without a purpose, with a plan on a RUNTIME context, without one
  on a provisioning context, with a malformed plan, or a provisioning answer carrying a market or organisation, is the
  Control Plane being outside the contract, so it is a retryable 503, never a guess. The purpose is stated, never inferred
  from the tenant's lifecycle. **Order of rollout:** this change must be deployed before the Control Plane emits the new members
  (ERP rejects unknown response members, ADR-ERP-010 section 15).
- **Per-route purpose.** `POST /provisioning-operations` and `GET /provisioning-operations/{operation_id}` accept only a
  `TENANT_PROVISIONING` context; the order-consequence and inventory reads accept only a `RUNTIME` one. A context of the other
  purpose is refused as the same indistinguishable 403 `ERP_CONTEXT_REJECTED` as every other context refusal.
- **Plan binding (independent of plan authority).** For a POST the plan the request names (`control_plane_authority`) must equal
  the plan the context is bound to, member by member, checked before anything is read or stored; the Control Plane assignment
  comparison (`PLAN_AUTHORITY_MISMATCH`) still runs unchanged afterwards, because context authority and plan authority are
  independent. For a GET the context's plan must equal the plan the operation was accepted under (stored on the command,
  columns that already existed), so knowing an `operation_id` or holding the tenant's context is not enough. Absence stays
  absence: another tenant's operation and an unknown one are still 404.
- **Caller rejections.** `PROVISIONING_AUTHORITY_NOT_CURRENT` (403) joins the codes that are about the caller's context
  (stale, withdrawn or superseded plan, or a provisioning not in an executing state) and is reported as 403
  `ERP_CONTEXT_REJECTED`, with its status; any other status for that code stays unavailable.
- **Unchanged.** No grant, no activation, no promotion of `baobab-cp-provisioning-workload` (still `PROVISIONED`). The Control
  Plane honours a provisioning context only for an ACTIVE provisioner, so the end-to-end evidence needs an environment decided by
  the owner (see baobab-cp#266); nothing here proves deployed validation.
