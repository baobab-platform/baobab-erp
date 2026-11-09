# ADR-ERP-001 — native engine conformance audit, initial increment

Audit date: 2026-11-09  
Decision: ADR-ERP-001 (Accepted)  
Implementation PR: ADR-ERP-001 private runtime boundary  
Scope: **development-only**; not staging, production, or general-purpose ERP certification

## Decision and baseline

ADR-ERP-001 establishes the iDempiere 13 / PostgreSQL 17 engine boundary. It
is deliberately an umbrella decision: implementation also depends on the
more specific ADR-ERP-002–022. ADR-ERP-023 (People/payroll) is a separate
extension, not a pretext for calling HR a completed ERP core.

The accepted native implementation is materially beyond the older
`architecture/conformance.yaml` snapshot. The merged ERP #125 real JVM
same-event proof is meaningful but expressly used synthetic buyer inputs.
The current draft ERP #132 contains posting/history/configuration guards
N0010–N0013 and must not be replaced, silently treated as merged, or
counted as accepted. Draft ERP #126 is experimental People only.

## Concrete defect corrected here

Before this PR, the checked-in `compose.yaml` used the short published-port
forms `${IDEMPIERE_HTTPS_PORT:-8443}:8443` and
`${BAOBAB_APP_PORT:-8000}:8000`. Without a host IP, these bind on all
host interfaces by default, bypassing the intended private network
boundary. Native HTTPS includes the iDempiere WebUI and may carry REST
plugins. The Baobab application API is likewise privileged.

This PR binds both published ports to **literal 127.0.0.1**, regardless of
operator-supplied published port numbers, leaving in-network Compose
service discovery unchanged. PostgreSQL remains unpublished. It adds an
architecture test for the source declaration and, when Docker Compose is
installed, the **fully interpolated** Compose model with nondefault port
numbers. Tests are automatically discovered by `scripts/validate.sh`.
This is a development topology safeguard, **not** a claim about security
of independent Infrastructure configurations, an authenticated gateway,
firewall rules, or any protected deployment.

## ADR-ERP-001 §109 acceptance ledger

Evidence labels: **Source present** is only a repo-level observation;
**Qualified** would require the named independent runtime proof on the
final relevant head. No requirement is marked fully qualified by this
assessment alone.

| # | Required acceptance | Current evidence / outstanding qualification |
|---|---|---|
| 1 | Reproducible iDempiere 13 runtime | Dockerfile and upstream.lock exist; mutable upstream `13-release` image/tag is **not** an immutable digest-pinned build receipt. **Open**. |
| 2 | No permanent upstream-core modifications | OSGi extension structure and patches policy exist; compare final runtime image and exception register in qualification. **Source present**. |
| 3 | ERP-private PostgreSQL | ERP-only Compose DB with no published DB port; independently verify credential and network isolation in protected topology. **Partial**. |
| 4 | Control Plane Engine registration | Provider descriptor in `.baobab/`; CP authoritative registered engine readback not supplied here. **Open**. |
| 5 | Registrable EngineInstance | ERP/native traces show an engine instance context; independently read back current CP instance lifecycle. **Open**. |
| 6 | IsolationProfile governing instance | CP context/assignment boundaries exist; independently verify selected profile and its routing effects. **Open**. |
| 7 | Canonical tenant/legal entity mapped to AD_Client | PostgreSQL mapping/provisioning code exists; real two-company placement and anti-cross-client tests remain needed. **Partial**. |
| 8 | Canonical mappings outside iDempiere | CP/Shared contracts and ERP mapping projection exist; verify CP authority and immutable native ID lineage. **Partial**. |
| 9 | Context resolution precedes routing | CP-aware runtime/finance code and tests exist; independently qualify all exposed command routes. **Partial**. |
| 10 | Cross-tenant isolation tests | Tests under `tests/tenancy` and native Gate B/D; full two-company read/write refusal remains a closure gate. **Partial**. |
| 11 | Bounded canonical ERP command executes | Real native order acceptance under merged #125; synthetic origin does not prove governed buyer/accounting outcome. **Partial**. |
| 12 | Business event uses canonical envelope | Outbox/inbox/Shared schemas exist, and the same-event path has run; native posted-fact event still needs qualification. **Partial**. |
| 13 | Retryable, idempotent event path | Native unknown-result adoption/replay proof in #125; complete financial reverse/replay cases pending. **Partial**. |
| 14 | End-to-end correlation preserved | Merged #125 exported graph covers a bounded Trade→ERP path; genuine BFF buyer origin remains pending. **Partial**. |
| 15 | Medusa only via API/events | Contract boundary and same-event transport exist; guard against all direct SQL/database coupling in connected run. **Partial**. |
| 16 | Payload independent from ERP DB | Explicit architectural contract; deployment-level DB access control to be independently verified. **Open**. |
| 17 | Native REST not Internet-exposed | This PR corrects default Compose host publication; separate gateway/network/security qualification remains. **Partial**. |
| 18 | Required container and dependency scans | Workflows exist; final PR-head and protected release receipts needed. **Open**. |
| 19 | Contract compatibility CI tests | Shared pin, conformance and CI infrastructure exist; final-head green run required. **Partial**. |
| 20 | Tested backup restoration | Restore plans and tests may exist; independent native accounting snapshot/restore and replay readback not established here. **Open**. |
| 21 | Documented LTS upgrade | Operations and upstream lock guidance exist; rehearse future upgrade without altering the canonical contract. **Source present**. |
| 22 | Distinct tenancy/legal entity/market/region semantics | ADRs and `docs/tenancy.md` document separation; verify native routing and isolation in live cases. **Source present / runtime partial**. |

**Result: ADR-ERP-001 is not development-complete.** This PR
remediates the concrete port-exposure defect and installs automated
regression guards. It must not change the accepted ADR text, turn
conformance status to `complete`, or activate staging/production.

## ERP development-complete gate (separate from ADR-001)

A narrowly defined **core** gate must independently prove: legal-entity
/ AD_Client isolation; governed Business Partner supplier/customer
projection; native GL/AP/AR; stock/warehouse/valuation; period, posting
and reversal vetoes; event deduplication and replay; committed-result
adoption; independently queried native ledger, documents and outbox/
inbox; and the same transaction/identity evidence across two companies.
No parallel synthetic ledger, manually seeded success receipt, or
framework-level unit test can replace native iDempiere PostgreSQL/JVM
readback.

The HR/payroll (ADR-ERP-023 / ERP #126), manufacturing and CRM extensions
have **separate named qualification gates**. They are neither silently
included in, nor a condition for misrepresenting, a working financial
ERP core. Real cross-engine integration, staging and production releases
remain separate later gates.

## Change / ownership boundaries

- ERP #132 owns N0010–N0013 native accounting-integrity guards and remains
  draft; this PR does not touch those migrations or its Gate B/D test drivers.
- ERP #126 owns experimental People persistence, still unqualified.
- Each later ADR receives an individually bounded implementation PR with
  evidence and explicit unresolved downstream dependencies; do not open
  empty PRs merely to reach a count of 23.
- Do not merge or mark ADR-ERP-001 complete on Compose-source evidence
  alone.
