# Baobab People — Frappe HR Payroll Entry read adapter (development integration)

**Status: source implementation only; NOT a qualified live Frappe provider, statutory payroll calculator, GL integration, payment or protected activation.**  
**Governing:** ADR-ERP-023, permanent BYOP, Shared ADR-SHARED-045 and CP-selected `payroll.run.read`.  
**Implementation:** `modules/people/providers/frappe_hr.py`.

## Operational boundary

The adapter is an optional external **REST consumer** of Frappe HR's Payroll Entry resource, not a dependency on ERPNext/Frappe as Baobab's financial ERP. Baobab's current native finance provider remains iDempiere. Tenants may retain other eligible payroll providers under accepted CP bindings.

It reads **one** payroll-entry metadata record: `name`, `company`, `docstatus` and `modified`. Neither source `docstatus=1` nor a successful read establishes payroll calculation correctness, statutory qualification, independent payroll approval, a native accounting journal or money movement. No employee, salary, tax, bank or payslip fields may be requested or returned.

## Trusted invocation and provider scope

Before constructing `FrappeHRPayrollRunReader`, a trusted employer-scoped provider registry/secret custodian MUST supply and independently attest:

- Expected canonical tenant, legal employer and work jurisdiction, taken from authenticated business context, **not** browser-provided fields;
- Exact provider ID and **binding ID plus binding revision** for the intended CP-selected provider;
- Exact opaque, registry-authorised `registered_source_run_ref`, not an arbitrary caller's Payroll Entry search string;
- Trusted Frappe HTTPS origin, company identifier and employer/provider-bound API key/secret; these credentials belong in a secret store, never a PR, CI log, frontend or environment-wide shared credential;
- CP workload credentials capable of retrieving fresh `payroll.run.read` selection from the independent Control Plane.

A reader is constructed for **one provider binding and one approved run**. `read_status(source_run_ref=...)` rejects a different run before CP or vendor transport. Every accepted call resolves CP afresh and refuses any tenant/employer/jurisdiction/provider/binding ID/**revision** mismatch or inactive/expired selection, **before** contacting Frappe. Rotation or migration requires a newly attested registry entry and re-instantiation; stale readers fail closed.

The Frappe request uses the `/api/resource/Payroll%20Entry` GET endpoint with explicit `name` and `company` equality filters and four allowed fields. TLS certificates are verified; proxies and redirects are disabled; response size, JSON keys and count are bounded; zero, duplicate, foreign-company or extra-data responses are rejected.

**The implementation does not yet provide the production registry/secret custody integration.** Configuring trusted credentials, binding them to the exact CP provider generation, rotating them and proving live source tenancy are separate required qualification tasks. Do not infer those capabilities from pure Python unit tests or from the optional `transport` test seam.

## Negative controls and qualification needed

Unit tests cover mismatched selected provider/employer, changed CP binding ID/revision, revoked CP selection, unregistered source run, missing/duplicate/foreign results, surplus PII fields, malformed source status and injection attempts.

Before enabling a real vendor account or advertising production support, produce independent evidence of:

1. Real CP/IAM workload identity, active selected binding and revocation/expiry/rotation; a fake selector is not evidence.
2. Real employer-scoped vendor credentials, no redirect/proxy/SSRF exposure, no cross-employer observation, and secret redaction.
3. Actual Frappe HR version/API fields/permissions, complete bounded HTTP responses, denied vendor permissions and timestamp/schema changes.
4. Lawful data residency, retention, minimal processing and provider incident/recovery controls.
5. Signed source/payroll evidence and independent statutory, accounting and payment qualification in their **separate** gates if those capabilities are subsequently requested.

Neither a selected Frappe provider nor this adapter overrides the platform's replaceable-headless-engine and provider-neutral product architecture (ADR-ERP-025).
