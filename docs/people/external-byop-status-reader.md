# Optional externally hosted HR-status source for Baobab People

## Scope and architecture

The optional provider adapter in ERP #156 is an *external* HTTP/REST client for a tenant-chosen HR system. The Baobab enterprise financial source of record remains iDempiere 13/PostgreSQL 17. A tenant's existing HR provider is neither automatically replaced nor allowed to become the tenant's default payroll source merely by configuring an endpoint. Provider-neutrality is governed by ADR-SHARED-045.

Every status read uses a fresh current CP selection for `payroll.run.read` under the exact tenant, legal employer, jurisdiction and registered provider identifier. CP must independently name the active binding, current revision, qualification receipt and valid lease. A refused or revoked selection stops the vendor HTTP request entirely; no token or vendor data may compensate for a CP refusal.

## Vendor source

The external source is addressed by an explicitly configured HTTPS base URL and private per-employer API credentials held in a tenant-authorised secrets manager. The read-only source operation uses the vendor resource API on the Payroll Entry document type, restricted to exact document name and exact registered company; only name, company, docstatus and modified are requested. Up to two records are fetched to refuse ambiguous matches. The adapter rejects unexpected fields, foreign companies, bad timestamps, nonexistent records, unexpected statuses, redirects, proxy usage, non-TLS transport and oversized data. The source can be DRAFT, SUBMITTED or CANCELLED, but these are *vendor document statuses*, not statutory approvals or salary payment authority.

Store the tenant/provider/account/credential reference mapping in a reviewed private integration registry. Never commit API keys, API secrets, employee details, salary slips, tax IDs, sample employee records or vendor-signed receipts to source control. This implementation consumes a vendor API when private credentials exist; **no real vendor account has been connected or independently qualified in this PR**.

## Acceptance progression

1. Standing development IAM workload registration approved in Shared #457.
2. IAM Ory credential provisioned with independent action-bound maker/checker approval (IAM #190).
3. Separate current CP employer grant, ACTIVE primary binding, approved release and independent EA-09 security and integration evidence.
4. Independent provider credentials supplied outside Git and actual external HTTPS readback witnessed in development, with source cancellation, revoked provider, sibling legal employer and replay refusals.
5. Current human CP proposal and separate checker approval (CP #479).
6. Statutory/localisation review and protected release remain HOLD until explicitly authorised.

**Non-claims:** no payroll arithmetic, bank file, GL posting, PAYE/UIF/SDL/ETI or URA/NSSF calculation, statutory certification, production deployment or default provider activation.
