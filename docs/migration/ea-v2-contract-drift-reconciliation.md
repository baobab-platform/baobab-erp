# EA v2 contract reconciliation — 2026-10-04

Target: Shared main `6899a2d8f143bf23d36c4f4ac904e0a1e10c3cea`.

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
