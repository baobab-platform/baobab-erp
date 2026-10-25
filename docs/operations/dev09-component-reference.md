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

## DEV-09 next increment: real PostgreSQL company/Organisation isolation

The native PostgreSQL Gate B suite now includes two additional transaction-backed
isolation tests (39 total): independent synthetic AD_Client/AD_Org pairs
(31/31, 32/32) have distinct Tenants, operating Organisations, Markets, legal
entities, immutable document provenance and native authority lookups. A foreign
AD_Client, a forged header AD_Org and an AD_Org owned by another native client
fail closed. Placement creation verifies actual iDempiere AD_Org ownership and
active state. All new fixtures roll back.

This proves **native JDBC/PostgreSQL transaction isolation rules**, not two
provisioned real iDempiere JVM companies, genuine Hydra/Kratos workload issuance,
production-verified legal standing, or an authorised provider. The original
39 ERP-A JVM assertions and 40 PASS / 8 BLOCKED development component receipt
remain separate and unchanged; it would be wrong to count these JDBC tests as
additional native JVM cases or to declare the independent-company obligation
fully qualified.

Next integration slices: (1) create two real independent iDempiere clients/orgs
through the approved test provisioning path and repeat positive/negative native
writes; (2) compose a genuine IAM-issued workload token with current CP Principal,
Tenant, Organisation, mandate and grant decisions and revocation/deactivation;
(3) connect Subscriptions current INTERNAL classification and live commercial
provider where available, and Payments simulated execution-evidence handoff.
Neither an ERP payment record nor a simulated Payments state implies bank/PSP
settlement. Absent sources remain explicitly BLOCKED; DEV-09/INT-08 and protected
acceptance remain open.

## DEV-09 Ory issuer / CP native authority increment (under qualification)

The additional reference stack runs IAM-source-pinned **real Hydra and Kratos
processes**, separate stores and a private TLS edge. The ERP workload token
uses Hydra client credentials with a run-registered exact audience and scopes;
Hydra's authenticated private token hook emits only workload actor/client
identity claims. CP verifies the signed token and decides its current operating
Context and per-native-operation legal authority. A dedicated probe reads back
Hydra registration, creates and reads two distinct Kratos identity records,
verifies CP accepts the authorised tenant/Organisation and refuses an unrelated
Organisation. Native S22/S23/S24/S25 still enforce CP mandate revocation,
scoped activities, outages and renewed authority, now using a Hydra workload.

Crucially, Kratos native human records in this ERP-specific harness do **not**
replace the synthetic CP administrative login fixture. That end-to-end human
administrative identity journey and legal-register evidence must not be called
qualified. No production IAM client is provisioned, no live company or legal
entity is modified, and no protected runtime is authorized. Exact IAM image and
source pins and bounded, run-owned credentials are mandatory; an unavailable
issuer or CP denies all posting.

### Second company native setup

Company B now requests actual iDempiere 13 `InitialClientSetup` process **53161**
inside the real JVM, using the documented native `ProcessInfo` parameter
contract with the default chart of accounts, South Africa and ZAR. The
reference refuses copied `AD_Client`/`AD_Org` rows: it accepts only a
successful native process result and independent read-back of native client,
organisation and accounting schema before a versioned ERP-owned CP placement.
Wrong-client placement and native-org reassignment remain denied. Neither
native company setup nor a CP mandate constitutes independent second-company
JVM GL posting; that next acceptance case remains **BLOCKED**, as do real
legal registration and all protected environments.

### Second-company real native GL posting proof — new mandatory DEV-09 gate

The dedicated disposable reference now requests a **real journal** for company
B through the shipped JVM/OSGi veto and native accounting engine. The Java
driver must use B's actual provisioned `AD_Client`, `AD_Org`, admin user and
native role; it may not use GardenWorld credentials for that operation. CP B
has the exact `ACCOUNTING_ENTITY` / `GENERAL_LEDGER_POSTING` mandate, not
an inherited Nabhold or company-A grant. The test refuses success unless:
(1) the native `GL_Journal` is completed and posted, (2) its `Fact_Acct`
rows are balanced and belong only to B's company and Organisation, and
(3) the native attribution names CP-persisted `AUTHORIZED` decisions for the
exact B Tenant, operating Organisation, legal entity, market, operation and
document reference. A missing accounting structure, permit, active period or
native journal is a failed test, not a skipped PASS. No finance authority
is derived from a native client or from successful initial setup.

The connected DEV-09 component receipt adds this assertion **only if the live
run observes all of it**. Original ERP-A evidence (39 independent purchase
assertions) and the earlier standalone GardenWorld Gate D must continue to
pass unchanged. Even with a successful second-company GL proof, Kratos-backed
human CP onboarding, independent verified legal data, subscriptions, Payments,
real bank/PSP settlement and protected staging/production remain unqualified.


### Fixture bootstrap precedes governed acceptance

Native account setup is deliberately not a catalogued protected financial
operation. Company B is created by the real native InitialClientSetup process
only in the disposable `integration` fixture-bootstrap JVM, before native
placements and migrations. The CI-only setup action refuses any other mode.
The stack then stops and recreates ERP in `acceptance` mode with the unchanged
shipped veto. Every GL/purchase/recording assertion runs after that restart.
The company-B journal reports its actual JVM mode; its proof is rejected unless
that mode is `acceptance`, the native ledger persists and CP independently
records the exact authorisation. This qualifies neither governed production
company provisioning nor permission to change accounting configuration.

The native default chart supplies document-controlled accounts. The bootstrap
therefore creates two labelled synthetic ordinary GL accounts and combinations
using MElementValue and MAccount, in B's own chart/schema and one transaction.
It never changes existing accounts' control flags. These are disposable test
accounting data, not a Finance-approved production chart or live legal fact.
