# DEV-09 ERP component reference

EA-DEV DEV-09 reuses the accepted native operation catalogue and ADR-ERP-022,
ADR-SHARED-037 and ADR-SHARED-038. It introduces no permission or provider contract.

The mandatory `erp-a-real-cp` CI job runs the existing real iDempiere 13 JVM,
PostgreSQL 17 and pinned CP binary. A test OIDC issuer, synthetic legal facts,
GardenWorld data and synthetic payment-execution evidence remain explicitly
synthetic. A payment record is never a disbursement or bank/PSP settlement.

`scripts/dev09_evidence.py report` accepts exactly S01–S26, S04b, S22b and
B01–B11 from that harness: 39 persisted native assertions. Empty, duplicate,
unknown, failed or skipped cases, wrong source/CP pins and missing built image
IDs refuse a report. The existing standalone Gate D job separately exercises GL
journals, balanced Fact_Acct, rollback and sales documents. It remains mandatory;
this receipt does not import its result or claim joined GL qualification.

Each invocation owns a fresh random Compose project. The EXIT trap preserves the
scenario exit status, collects and scans logs, removes that project's containers,
volumes and networks, removes its temporary directory and independently queries
Docker for surviving labelled resources. Cleanup failure fails CI. A log-redaction
failure still attempts teardown. Fixed loopback ports remain: concurrent invocations
on the same host may fail on port binding, but cannot delete each other's projects.
Images and the host are outside this cleanup claim. `GATE_D_KEEP=1` produces no
successful DEV-09 cleanup receipt, so it cannot qualify this profile.

Only after successful scenarios and teardown does CI generate the original
sanitised `dev09-report.json` and its SHA-256 companion, uploaded separately as
`dev09-erp-components`. The closed projection omits raw request/response details,
SQL, credentials and temporary paths. Failed reruns delete previous output before
validation. The original ERP-A forensic artifact remains separate.

A successful component run has **40 PASS / 8 BLOCKED**: 39 native assertions and
one run-owned teardown, plus eight joined obligations. Overall DEV-09/INT-08 is
BLOCKED. Current estate IAM authority, independent company/org isolation, joined
GL provenance, Subscriptions current INTERNAL authority, commercial Kill Bill,
Payments simulated lifecycle, external settlement and Trade COMMIT are not proven
by this profile. Kill Bill is not implemented; no fake commercial readiness,
settlement, entitlement, production authority or protected acceptance is inferred.

Subscriptions onboarding remains separate. DEV-06/INT-07 resumes only after that
onboarding, with current CP binding/resource enforcement and all original negatives.

Unit tests exercise rejection and sanitisation only; they are not native evidence.
Only a successful final-head owner CI run supplies real-component observations.
