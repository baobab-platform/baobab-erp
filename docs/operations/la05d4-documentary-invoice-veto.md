# LA-05D4 — ERP customer-invoice documentary remediation veto

**Status:** bounded, nonproduction consumer implementation. Not production-certified.

The guarded `order_to_cash.governed_service.post_customer_invoice_governed`
boundary now REQUIRES three independent sources before invoking native
iDempiere customer-invoice posting:

1. Fresh, scoped CP `legal-actor:assess` verdict for the legal **INVOICE_ISSUER**
   (existing LA-05D3);
2. The current CP `documentary:restriction-assess` **negative veto**
   for the exact canonical runtime Context, operating Organisation, market,
   capability `accounting.customer-invoice.post` and invoice operation reference;
3. Independently certified native accounting/provider readiness, including
   verified iDempiere company and finance baselines (LA-05D).

The documentary veto is checked twice: before native provider readiness
and immediately afterwards, **before** invoice posting. CP HTTP failures,
missing evidence, scope/context mismatches, stale leases, active holds and
issuer/merchant denial fail closed. The response's `blocked:false`
and `authority_granted:false` are **NOT** a legal or finance grant.

`HttpControlPlaneDocumentaryRestrictionAssessor` requires a private HTTPS
Control Plane origin and genuine IAM-issued ERP workload access token;
it rejects duplicate JSON fields, oversized responses and invalid/missing
credentials. The workload must be explicitly registered in CP with the
`documentary:restriction-assess` scope, must own the supplied
canonical bounded runtime Context, and must be allowlisted by the CP service.
Never use a human/applicant token or frontend-selected endpoint.

## Required further execution closure

The older direct `order_to_cash.service.post_customer_invoice` entrypoint
is still available for historical compatibility. The current guarded wrapper
is not automatically called by every iDempiere execution path, so **LA-05 is
not complete** and native posting MUST NOT be treated as certified. A
subsequent activation gate must inventory and migrate every consequential
live caller, including legacy/maintenance paths, enforce private network
routing, inspect the native plugin baseline, validate a deployed staging
readiness adapter, and demonstrate that direct bypass is impossible.

The code/CI tests are synthetic only; they do not verify a live CIPC company
record, registered legal mandate, Regulations rule, iDempiere finance baseline,
or real customer invoice posting.
