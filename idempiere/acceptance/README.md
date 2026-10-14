# Gate D — real iDempiere posting harness (CI only, never shipped)

EA v2.1 / P0-04B ERP (ADR-ERP-022 §7). Proves the posting-authority path on a **real** iDempiere 13 and
PostgreSQL, not a fixture. Atomic posting may be called verified only from a green run of the CI job
`idempiere-posting-integration`.

| File | Role |
|---|---|
| `Dockerfile` | Adds the driver bundle on top of the deployable image built from `idempiere/Dockerfile`. The shipped finance veto runs unmodified. |
| `driver/` | `org.nabhold.baobab.erp.acceptance`: inside the iDempiere JVM, it reads request files and drafts, completes and posts GardenWorld GL journals through `MJournal.processIt` and `DocumentEngine.postImmediate`. |
| `synthetic_cp.py` | A **synthetic** CP/IAM over TLS (CI-generated CA). It serves context, posting-authority and documentary responses chosen by a mode file. It holds no mandate and is never evidence of legal standing. |
| `run-gate-d.sh` | Starts a fresh PostgreSQL (the upstream entrypoint imports GardenWorld), the synthetic CP and the image. Applies `db/migrate.sh` and `db/migrate-native.sh`, then seeds a synthetic placement and Finance baseline. Runs each scenario and asserts **persisted** state with `psql`. |

## Setup

An operator does the following before any scenario runs:
- switches GardenWorld to standard period control;
- opens the current GL period;
- records one placement for client 11 / org 11;
- records a Finance baseline for the synthetic legal entity.

## Scenarios

Every refusal must carry `BAOBAB_NATIVE_FINANCE_DENIED`. Every direct-SQL bypass must change a real row
before COMMIT.

- **Valid authority.** The journal reaches `CO` and is posted. `Fact_Acct` is balanced, and the attribution row carries the CP `decision_id`.
- **Authority is lost between draft and completion.** The modes are: no mandate, revoked, another legal entity, another tenant, another market, another operation's role or activity, an expired lease, and a documentary hold. In each case there is no `CO` and no ledger.
- **Native org with no placement.** The document cannot be created.
- **Failure injected after `Fact_Acct` rows are written, before commit.** No journal, ledger or attribution survives.
- **Three concurrent postings.** Each is posted, balanced and attributed in its own transaction.
- **Retry after commit.** No duplicate ledger.
- **Background forced repost** (the accounting-processor path, in its own transaction):
  - under authority, the ledger is rebuilt and newly attributed;
  - after revocation, the repost is refused and the committed ledger is intact.
- **Direct SQL** `Fact_Acct` insert and direct SQL completion are both refused at COMMIT by the database fence.

## Running locally

Run `idempiere/acceptance/run-gate-d.sh <image> <work-dir>`. It needs `docker`, `psql`, `openssl` and
`keytool`. Set `GATE_D_KEEP=1` to leave the containers up for diagnosis. The report, the iDempiere log, the
synthetic CP log and the migration log are written to `<work-dir>`.
