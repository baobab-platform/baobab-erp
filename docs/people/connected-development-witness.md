# DEV-PPL-01 — connected People provider selection (development only)

**Status:** implementation candidate, gated by exact-head **People DEV IAM–CP–ERP connected provider-selection witness** CI. **Not** payroll, statutory, or protected release qualification.

## Real components and boundaries

This integration deliberately extends the already-qualified ERP-A disposable container topology rather than introducing a second IAM, message bus or CP implementation. The runner builds the actual CP binary at the independently reviewed **CP #478 companion candidate** `eca7d896d408ee4880dac50af988ecec1672a214`, pins the current IAM-owned Ory configuration at `39fc7bcb3fd0568e09f1304e6fe07e64ba31c5bf`, launches genuine Ory Hydra (plus Kratos), the real CP PostgreSQL 17 schema, and ERP's actual `people.providers.selection.CPProviderSelector` from the source tree. The ERP consumer calls CP's real read-only People route through a throwaway-CA authenticated TLS endpoint. Its granted bearer comes from Ory's live client-credentials endpoint, not hardcoded JSON test replies.

**Precisely scoped limitation:** the ERP-A harness uses a **test-only** Ory token-profile hook/CP administrative issuer, not a deployed IAM workload registration. This job separately executes IAM's `internal/tokenprofile` positive/negative People issuer policy tests; it must not claim that a production IAM token-profile hook or governed employer onboarding was witnessed. The People client and CP registry entry exist **only inside the disposable containers**; neither changes Shared registry nor provisions an actual employer or payroll provider.

The accepted Shared capability remains `DRAFT`. A temporary `ACTIVE` capability projection and synthetic `CERTIFIED` provider/release row are necessary to exercise CP's genuine resolution algorithm, and are permitted **only inside the throwaway CP test database**. They are not real EA-09 or statutory evidence. The script explicitly restores the capability to `DRAFT` after the scenarios and asserts no duplicate choice rows.

**Companion acceptance:** CP #478 corrects the authoritative Context resolver's missing country-level `jurisdiction`; until CP #478 is independently green and merged, the ERP CI pins its exact review SHA, not an accepted CP release. Before merge, re-pin the new merged CP commit and obtain a fresh final-head end-to-end receipt. The prior real run on ERP head `856980631893f69276f0aefadb57ad4c5ae002e1` correctly failed with `PEOPLE_DEV_WITNESS_CONTEXT_DB_LINEAGE` because a resolved country did not populate jurisdiction. The test must never solve this by writing the jurisdiction into the Context table by hand.

## Required witnessed cases

| Case | Meaning | Required CP HTTP |
| --- | --- | --- |
| PPL-01 | Ory-scoped People token, current CP context, employer binding, real ERP read | 200 |
| PPL-02 | Same bearer and Context replay; new read decision, same single choice | 200 |
| PPL-03 | Foreign tenant/organisation Context has no inherited People choice | 403 |
| PPL-04 | ERP-requested employer differs from real CP employer | 200 (ERP independently denies) |
| PPL-05 | Ory token lacks `people:provider:read` scope | 401 or 403 |
| PPL-06 | Revoked certification denied while old bearer remains valid | 403 |
| PPL-07 | Repeated selection after revocation remains denied | 403 |

Independent PostgreSQL readback checks the same employer-scoped choice, binding, provider, grant, lease context and **persisted immutable resolution decisions**, in addition to HTTP statuses. CP denial must be a proven HTTP 401/403; a connection error, timeout, wrong status or malformed response **cannot count as a negative PASS**. Each successful read uses the existing CP authority resolver and CP re-reads the committed choice for revocation/cutover fencing.

## How to reproduce

Run the dedicated CI job from the PR, or use the same exact CP/IAM checkouts and prepared ephemeral Docker environment as `idempiere/acceptance/erp-a/run-gate-d-erp-a.sh` with:

```bash
BAOBAB_ENVIRONMENT=integration PEOPLE_DEV_CONNECTED=true \
  ERP_IMAGE=baobab-erp:gate-d \
  CP_SRC=/path/to/pinned/baobab-cp \
  CP_PEOPLE_WITNESS_SHA=eca7d896d408ee4880dac50af988ecec1672a214 \
  IAM_SRC=/path/to/pinned/baobab-iam \
  IAM_COMMIT=39fc7bcb3fd0568e09f1304e6fe07e64ba31c5bf \
  idempiere/acceptance/erp-a/run-gate-d-erp-a.sh /path/to/private-evidence
```

The runner generates ephemeral credentials, refuses protected environments, independently checks the persistent state, sanitizes the receipt and deletes the Compose project, volumes and private run directory on exit. Its artifact contains **no** bearer, client secret, signing key, payroll employee information or raw SQL output. A separate normal ERP-A run is unchanged: `PEOPLE_DEV_CONNECTED=false` by default, and the People consumer is not mounted.

## Reserved release gates

Even if all seven cases pass, **statutory ZA PAYE/UIF/SDL/ETI and UG URA/NSSF qualification remains HOLD**, as do licensed source-provider account onboarding, employer data-processing authority, employee privacy/residency evidence, live adapter signature custody, external-provider cutover, payroll calculation, return filing and accounting or money movement. None of these may be inferred from Ory token issuance, a synthetic provider certification or a merged test harness. A real IAM-approved People workload, CP governance/maker-checker mutation, release policy, issuer/consumer revocation and production provider implementation require independent work and acceptance.

**Evidence classification:** `DISPOSABLE_SYNTHETIC_DEVELOPMENT`; source claims must not exceed the independently observed CI run and persisted PG17 facts.
