# Baobab People — Independent BYOP Qualification Status

**Assessment date:** 8 November 2026
**Governing contract:** Accepted Shared ADR-SHARED-045 / Shared #434
**Engineering candidates:** Shared #436 · CP #466 · IAM #157 · ERP #126
**Decision:** **HOLD — NOT STATUTORILY OR RUNTIME QUALIFIED**
**Protected staging/production activation:** **NOT AUTHORISED**

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
| IAM/OIDC issuance | HOLD | HOLD | Current real workload audience, scopes, token validity, expiry/revocation readback and no tenant/provider claims |
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
