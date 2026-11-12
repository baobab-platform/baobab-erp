# Baobab People — Independent BYOP Qualification Status

**Assessment date:** 8 November 2026
**Governing contract:** Accepted Shared ADR-SHARED-045 / Shared #434
**Engineering candidates:** Shared #436 · CP #466 · IAM #157 · ERP #126
**Decision:** **HOLD — NOT STATUTORILY OR RUNTIME QUALIFIED**
**Protected staging/production activation:** **NOT AUTHORISED**
**Development code merge:** **ELIGIBLE only after exact-head CI and code safeguards pass; statutory/provider certification is not a source-merge gate.**

## Development/release separation — 12 November 2026

The engineering programme explicitly permits **merging inert source and reproducible disposable integration tests** before the independent payroll provider and statutory review are completed. This does **not** change the HOLD decision for operating payroll, external live-provider processing, employee-data custody or staging/production activation. No migration or provider can become operational merely because this branch is merged.

**Development merge checks:** exact-head CI; real disposable PostgreSQL 17 immutable workforce/payroll draft CAS, correction and concurrency negatives; real iDempiere 13 ERP-A no-side-effect check; Shared-045 canonical People vocabulary; independent CP authority reader and IAM scoped workload adapter that fail closed without approved binding; provider- and reviewer-signature verification including forged/stale/revoked and foreign employer negatives; preserved zero-default capability registration and protected environment fences. CP #466 contains the complementary development-only reader; its **source-merge** is a prerequisite for treating the ERP adapter as reconciled, not a claim that any current employer actually has an ACTIVE choice.

**Deferred until protected staging/production release:** actual country-specific ZA/UG statutory golden vectors and licensed qualified providers; live issuer-issued People token and CP-governed employer/provider choice with maker/checker; independently witnessed employee privacy, vendor source receipts, provider cutover/replay, supervised pay runs, accounting/Payments effects and EA-09 release. These remain blocked by explicit capability DRAFT status, empty/default-deny qualification trust, disabled experimental migrations and absent production People binding.

**Acceptance semantics:** DEVELOPMENT SOURCE MERGED != RUNTIME PROVIDER QUALIFIED != STATUTORILY CERTIFIED != STAGING/PRODUCTION RELEASE AUTHORISED. Keep the original independent qualification matrix below as release evidence required, not as a prohibition on version-controlling inert code.


## Engineering readback

- Shared capability vocabulary: four DRAFT/EXPERIMENTAL People keys and provider-selection readback, Accepted as **contract semantics only**.
- CP: employer/capability/jurisdiction/effective-window choice; disabled-by-default readback and PostgreSQL uniqueness constraints. No qualified active choice has been witnessed. CP changeset/approval mutation is not yet integrated.
- IAM: exact development workload scope pair and CP audience; no runtime grant, client registration or credential issuance witnessed for People.
- ERP: optional native draft-only store and external HTTPS anti-corruption adapter verifying original provider Ed25519 receipts; provider and employer are pre-bound and checked against current CP selection. No real provider endpoint/client credentials/employee data has been registered.
- Independent statutory checker: **absence of trust keys or external signed review denies**. Synthetic reviewer signature tests demonstrate only structural and cryptographic code behavior. Real review custody and legal truth remain unverified.

## Required independent evidence before changing HOLD

| Qualification dimension | ZA | UG | Required evidence |
| --- | --- | --- | --- |
| Legal employer authority and statutory registration | HOLD | HOLD | Independent legal entity and employer registration readback |
| Licensed/contracted source provider | HOLD | HOLD | Provider agreement, verified account binding and right to process |
| Statutory rules | HOLD | HOLD | ZA PAYE/UIF/SDL/ETI and UG URA/NSSF **separate** signed, effective-dated expert reviewed golden vectors and official source references |
| Worker and data protection | HOLD | HOLD | Approved retention, lawful purpose, residency, encryption and deletion/export proof |
| Independent parallel calculation | HOLD | HOLD | At least two actual witnessed source-versus-expected pay runs per jurisdiction, including correction and zero/negative cases |
| IAM/OIDC issuance | HOLD | HOLD | Independent issuer readback confirms real workload audience, scopes, token lifetime, expiration and revocation; verifies no tenant or provider claims |
| CP binding + provider resolution | HOLD | HOLD | Actual PG17 current legal employer + provider + EA-09 and statute evidence, positive and revoked/mismatched negatives |
| ERP signed provider receipt | HOLD | HOLD | Actual registered provider public key, source run/version/binding result, replay and wrong-employer refusal |
| Disruption/cutover/export | HOLD | HOLD | Source outage, no hidden fallback, historical lineage, effective date, migration-out/readback, replay |
| Consequential posting or bank release | NOT REQUESTED | NOT REQUESTED | Requires separate ERP posting / Payments approval if tenant elects those services |

## Acceptance standard

**Do not** promote status from synthetic test, green CI, schema validation,
unsigned vendor claim, mock payment, hypothetical statutory rates, source-only
trace or local PostgreSQL migration to legal/payroll qualification.

The independent verifier must read actual source-authored records, actual
IAM/CP current authority and genuine PG17 state; all recorded evidence must
be independently retained, attributable, replay-safe and inspected by
different principals. A real jurisdiction-specific statutory assessor must
approve immutable rule digests and correction treatment. The final report
must reference exact commit SHAs, provider IDs, test instants and signed
witness manifest. None is available yet for People; this file is a
deliberate refusal to issue a false acceptance.

**No real employee/payroll data is necessary in source control.** Sensitive
evidence stays in approved tenant-specific custody and can be represented
here only by opaque references and independently verified hashes.
