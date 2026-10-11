# LA-05D4 — close the legacy ERP invoice-post legal actor bypass

**Authority:** Accepted ADR-BCP-027 LA-05/LA-T06–T14, and ADR-BCP-026 PEO-T09/T22. This is Package 4 consumer boundary implementation, not production certification.

## Prior bypass

The old `order_to_cash.service.post_customer_invoice` path resolved the invoice from a `TenantScope` and invoked iDempiere posting directly. `TenantScope.legal_entity_id` is a routing selector, not current evidence of the actual INVOICE_ISSUER legal person. The newer `governed_service.post_customer_invoice_governed` performs CP, documentary and provider checks but was opt-in: callers could still execute the old function in staging and production.

## New protected boundary

1. **Deny by default:** without an explicit `BAOBAB_DEPLOYMENT_ENV=development|test`, staging/production/unknown runtimes deny public legacy `post_customer_invoice` BEFORE resolving mappings, invoking iDempiere or writing the outbox. `BAOBAB_REQUIRE_LEGAL_ACTOR_GATE=true` additionally forces denial even in local dev/test.
2. **Current CP authority:** the permitted route is `post_customer_invoice_governed`; it validates exact Tenant/operation/invoice/role/capability and current CP assessment; checks separately governed provider and documentary restrictions, then rechecks CP at point of use.
3. **Ephemeral exact operation permit:** only once the final checks succeeded, the wrapper uses a private in-process `ContextVar` scope tuple `(tenant_id,legal_entity_id,invoice_canonical_id)` while invoking the native command. It is reset even after exceptions and cannot leak to another thread/task, sibling Tenant, invoice or legal person. An HTTP-supplied `governed:true` flag is not accepted.
4. **Legacy compatibility only for tests:** historical native-unit fixture uses explicit `BAOBAB_DEPLOYMENT_ENV=test`; production environments must not permit the test marker in deployment governance. This compatibility escape is only a code-path testing tool, not a security capability or alternative to CP.

The in-process ContextVar prevents accidental *internal* legacy call-path bypass; it is not an IAM credential, a sandbox against arbitrary Python code running with process privileges, or a substitute for authenticated workload requests, real iDempiere provider validation and network policy.

## Acceptance tests

- Direct legacy invoice post in staging/production/unspecified runtime denies before any native process or outbox side effect.
- Wrong Tenant, legal entity or invoice cannot reuse an already checked permit; permit disappears after the invocation.
- A governed invoice post can enter native execution only after both current CP facts and documentary/provider readiness checks.
- Denied/revoked legal actor, remediation imposed after readiness, provider outage or scope mismatch never calls the native posting function.

## Still outstanding in Package 4

Other financial mutations (sales-order posting, shipment completion, payment accounting), canonical event ingestion, vendor-specific live iDempiere execution, Trade Medusa native legal-seller guard, Payments PSP certification, and any remaining direct consumer route must be audited and closed per operation. This PR closes **the identified invoice-post bypass**, not every possible cross-engine action.

**Live acceptance remains blocked** by authentic IAM-backed CP assessments, current official legal-actor mandates, trusted iDempiere company mapping and protected staging provider proof.
