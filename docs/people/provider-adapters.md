# Baobab People provider adapters — first implementation increment

**Status: DRAFT/HOLD; no live provider qualification or statutory certification.**
The accepted contract is Shared ADR-SHARED-045 / #434; companion development
work is Shared #436, CP #466 and IAM #157. This increment builds an
execution-capable provider-neutral **verification** boundary, but it is not
an operational payroll service.

`people.providers.selection.CPProviderSelector` sends *only* context,
capability, correlation and contract-version intent to CP; it obtains a
workload token for the **exact** `baobab-control-plane` audience and
`context:resolve people:provider:read` scopes. It verifies the resulting
tenant, employer, jurisdiction, provider/binding IDs, revision, short
effective window, completion and portability. No provider can select
itself and no fallback provider is implicit. The default HTTP transport
requires TLS, verified certificate, no proxy, no redirect, bounded
response, and refuses untrusted fields/duplicate JSON members.

`people.providers.evidence.ExternalEvidenceAdapter` is a **private
anti-corruption adapter** protocol, not a new published Shared API. A
privately configured HTTPS service verifies a source payroll receipt
and responds with a limited signed canonical metadata payload.
An Ed25519 key pinned in the employer's qualified adapter configuration
verifies the original source receipt. The adapter rejects a result signed
by a different provider or carrying another tenant, employer, country,
run version, rule digest, binding revision or qualification reference.
Signed evidence is not permission to post/pay.

`SelectedCalculationVerifier.verify_draft` checks the immutable ERP
draft and reads CP choice anew, delegates only to its selected adapter,
and then independently rechecks statutory qualification. The separate
`QualificationRegister` defaults to **DENY** until a live independent
verified evidence reader is installed. The current `PayrollEligibilityGate`
interface deliberately cannot be silently replaced with this object;
a future guarded command handler must load the exact draft and call
`verify_draft`, then perform a separate IAM employer maker/checker and
native ERP/payment boundary, never a fabricated receipt.

The native PG17 scaffold has **no** payroll calculator and the
`NativeDraftOnlyAdapter` always denies final verification. BYOP providers
operate independently; Baobab never requires iDempiere accounting or
Baobab Payments for externally owned runs.

## Independent qualification gates

- ZA: independently approved PAYE/UIF/SDL/ETI golden cases, source identity,
  licensed/statutory provider evidence, reviewer independence and ≥2 witnessed
  parallel pay runs (including correction/refund/replay negatives).
- UG: separately approved URA/NSSF regime and vectors; ZA evidence cannot
  qualify UG. Cross-border residence and data handling require their own legal
  approvals.
- Runtime: real IAM token, CP selected active provider and legal employer,
  actual registered adapter, qualified signed receipt, no duplicate or
  implicit fallback, replay, cutover/export, time-of-check/use revocation,
  encrypted evidence custody and independent database/log/trace readback.
- Never treat synthetic signed tests as proof of statutory compliance,
  provider licensure, bank release, iDempiere GL posting or production readiness.

No payroll provider keys, URLs, secrets or private employee data are
committed. No provider is registered or activated.
