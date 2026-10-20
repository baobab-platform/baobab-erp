# ADR-ERP-023 — Baobab People: African Workforce, Payroll, CDSoftware Re-engineering and PostgreSQL 17

**Status:** Accepted — ERP-local architecture and engineering direction, 20 October 2026. Shared contract, statutory, provider and production approvals remain separate and pending.
**Decision class:** ERP / People / Workforce / Payroll / Africa localisation / Third-party plugins / Database baseline
**Repository:** baobab-platform/baobab-erp
**Owner:** Baobab ERP engineering; Shared owns canonical contracts; Control Plane owns entitlement/binding/runtime authority
**First consumers:** Nabhold Group Africa; later independently onboarded Baobab organisations and external customers
**Related:** ADR-ERP-001/002/003/004/005/006/007/008/009/010/011/013/017/018/019/020/022; Shared ADR-0005, ADR-SHARED-007/017/021/033/034/036; Nabhold Go-Live Masterplan v2.0 (G07/G08); accepted Baobab EA implementation architecture

## 1. Decision

1. **Baobab People SHALL be developed and operated within baobab-platform/baobab-erp.** It is a domain/product family, not a new canonical Engine, a separate Git repository, an automatic separate Tenant, or an independent financial system of record. A distinct commercial experience may consume its canonical capabilities.
2. **The existing CDSoftware iDempiere HR/Payroll plugin family SHALL be evaluated as a candidate implementation foundation.** ERP engineering MAY refactor, modernise, adapt, port, replace components of, or re-engineer that plugin family when justified by iDempiere 13 support, security, maintainability, tenant separation or African localisation. It SHALL NOT imply permission to fork iDempiere core, bypass licence conditions or install unreviewed upstream artifacts.
3. **The ERP runtime target is iDempiere 13 (Orion) with PostgreSQL 17 and Java 17.** All new first-party People functionality and qualified CDSoftware components SHALL work against that tested tuple. PostgreSQL 16 deployments and volumes require a controlled major-version migration, not an unqualified image swap.
4. **Workforce, time/attendance, payroll calculation, payroll approval, statutory filing, financial posting and payment execution SHALL remain separately governed capabilities and authorities.** A feature may use a CDSoftware implementation without exposing a CDSoftware-native API or vendor identity through canonical contracts.
5. **South Africa (ZA) SHALL be the first independently qualified payroll localisation; Uganda (UG) SHALL be the next design target.** Further countries require separate evidence and certification. No country pack SHALL be assumed compliant from configuration or source-code completion.
6. **Nabhold's initial payroll SHALL preserve the provider-first contingency.** No March 2027 employee pay run depends on the success of the CDSoftware commercial R&D programme. A qualified external payroll service or bureau remains an acceptable bounded provider behind the ERP-owned People boundary until native payroll is independently certified.
7. **No source, branch, plugin version, certification claim or production activation is created by this ADR.** Engineering evidence, independently accepted statutory/provider evidence, EA-09 certification and CP-controlled capability activation are distinct.

This decision refines the previously proposed workforce/payroll classification in the ERP capability census. It does not retroactively assert that either is already implemented.

## 2. Context and evidence baseline

Nabhold's accepted v2.0 masterplan makes Workforce/HR (G07) and Payroll (G08) part of the R1 protected corporate workplace. The 19 October go-live register records both gates blocked pending accepted contracts, provider support and statutory evidence. The ERP capability census as of 8 October lists Workforce and Time/Attendance as proposed and Payroll as out-of-scope until staffing needs; this decision supersedes that *planning priority*, not the reported implementation state.

At this decision date, upstream.lock.yaml selects idempiereofficial/idempiere:13-release (Orion), Java 17 and PostgreSQL 16; some acceptance tests already use PostgreSQL 17. Official iDempiere 13 development guidance uses PostgreSQL 17 and Java 17. CDSoftware's public Payroll page names older iDempiere compatibility; recent Attendance documentation explicitly references a Payroll 12.0.0 dependency, and a separate CDSoftware plugin documents v13 testing. **CDSoftware Payroll on iDempiere 13 is unproven.** Source dependency manifests, tests, supported-release matrix, 2Pack content and licences must be independently inspected before any executable adoption.

Commercial intent is to create a reusable African HR/payroll and employer-compliance offering for independently governed companies, not merely Nabhold's internal payroll.

## 3. Architectural boundaries and ownership

| Concern | Authoritative boundary |
| --- | --- |
| Canonical capabilities, schemas, event semantics, versions and namespace | Shared; ERP proposes but SHALL NOT mint catalogue keys |
| Organisation, Tenant, LegalEntity, legal-actor mandate, market context, provider binding and effective grants | Control Plane |
| Human/workload authentication, step-up and tokens | IAM; employment SHALL NOT automatically grant a platform account or access |
| Employment record, workforce lifecycle, position, leave and approved payroll input semantics | ERP-owned People provider, under accepted Shared contract |
| Payroll statutory calculations and detailed result | Qualified People-native country pack OR independently qualified external payroll provider, exactly one authoritative result per pay-run/version |
| Payroll approval and versioned accounting handoff | ERP People orchestration; approval authority is independently attested |
| General ledger, journals, liabilities, cost centres, financial reconciliation | ERP/iDempiere, including native posting veto and period controls |
| Bank-money movement, authorisation, disbursement and settlement | Independent approved Payments/Treasury boundary; a payroll approval is not a bank-release grant |
| Regulatory source/evidence and governed requirement evaluation | Regulations, with expert decisions and source provenance; local payroll law is not invented by ERP |
| Intelligence, research and change-detection signals | Pulse; advisory only, no automatic statutory rule promotion or employee-level data mining |
| Confidential documents, employee contracts, payslips and source evidence | Approved documents/custody capability consistent with ADR-ERP-017 and POPIA |

The ERP People implementation SHALL take Organisation, Tenant, LegalEntity and Market from attested current CP context, supplemented by a verified employment/payroll relationship, and SHALL resolve vendor AD_Client/AD_Org and employee IDs through private mappings. Employer legal identity, work jurisdiction, tax residence, benefit regime and place of work are distinct effective-dated facts. Caller-provided vendor identifiers SHALL never establish authority.

Corporate ownership, shared cloud infrastructure, cross-company transfer or group reporting does not give Nabhold or one subsidiary access to another employer's employee records. Group reporting requires separate grants, lawful purpose, classification and defensible aggregation.

## 4. Internal implementation and CDSoftware strategy

Implementation lives in baobab-erp, initially under:
- idempiere/extensions/org.nabhold.baobab.erp.people/ — narrowly scoped first-party OSGi integration and enforcement;
- idempiere/vendor/cdsoftware/ — governed source references, immutable artifact manifests, provenance and a reviewed patch series only as licensing permits;
- modules/people/workforce/, payroll/, providers/, localisation/ and reconciliation/ — modular ERP-owned services and tests;
- tests/people/ and docs/people/ — conformance, statutory-fixture and release evidence.

These paths are a target layout, not an instruction to create empty placeholder bundles or a claim they exist. Separate first-party OSGi bundles SHALL be created only when required by a proven extension point. Third-party packages SHALL be installed reproducibly through supported p2/OSGi/2Pack mechanisms, never manually edited in a production container.

CDSoftware treatment:
1. Prefer a maintainers' supported iDempiere 13 release if independently verified, rather than an unnecessary fork.
2. If unavailable, maintain a documented CDSoftware compatibility/port patch series with upstream source commit, exact dependency tree, semantic changes, tests, reviewer, licence and upstream contribution strategy. Vendor patching does not relax ADR-ERP-004's ban on a long-lived *iDempiere core* fork.
3. Refactor unsafe hardcoded role, AD_Client, AD_Org, employee, process or country IDs; replace insecure direct SQL and undocumented ERP internals; repair OSGi dependencies, generated models, Application Dictionary/2Pack packages, schema migrations, reports and lifecycle logic.
4. If an upstream component is irreparably unmaintainable, replace it with a Baobab-owned implementation behind the SAME canonical capability; record the rationale, evidence and migration/rollback in a reviewed ADR amendment. No sunk-cost mandate to preserve every CDSoftware module.
5. Record and validate SPDX/licence notices, source provenance, modification attribution, source-offer obligations where distributed, SBOM, vulnerability status, dependency trust and commercial-hosting/distribution legal review. GPL licensing is neither prohibited nor a blanket proprietary exemption.
6. Resolve all dependency/version conflicts, and prove a complete synthetic pay-run in an actual iDempiere 13 + PostgreSQL 17 runtime before implementation status can advance beyond experimental.

Neither a successful OSGi ACTIVE state nor a successful 2Pack import is proof of valid payroll accounting, statutory localisation or production permission.

## 5. Capability and contract programme

ERP engineering SHALL sponsor a Shared namespace/capability census for distinct Workforce, Attendance and Payroll functions. Proposed semantic functions include: employee and employment-record lifecycle; organisation/position/manager; approved leave and attendance; earnings/deductions input; payroll-period lifecycle; draft/validate/approve/finalise/correct runs; restricted payslip; statutory output; aggregate journal handoff and reconciliation. **No proposed spelling here is a canonical capability key.** Shared shall decide registered domains, contract shapes, event types and compatibility policies (ADR-SHARED-007/017).

Canonical contracts SHALL specify effective time, immutable employment version, legal employer, jurisdiction, currency, rule-pack version, period, provenance, approval identity, idempotency, correction/reversal semantics and partial/withheld/complete information states. Monetary values SHALL use decimal strings and prescribed rounding, never binary floating point. Provider IDs SHALL remain private external references. No bidirectional mutable master-data synchronisation by default.

Compensation events and statutory calculations SHALL be auditable and reproducible by pay-run, employee, rule-pack hash, effective date and relevant source-evidence revision. Correction of historical payroll SHALL not silently recompute with current rates; an amended/corrected payroll run shall preserve lineage.

## 6. African statutory localisation

Country packs SHALL be separately versioned and governed: ZA first, UG second, and subsequent jurisdictions by independently established demand and jurisdiction evidence. A legal employer may be associated with several employment/tax jurisdictions; Market does not stand in for statutory jurisdiction. Distinguish employer entity, payroll registration, income-tax jurisdiction, employee tax residence, work location, contribution scheme, pay currency and reporting obligations.

A localisation pack may include:
- effective-dated statutory tax/rebate thresholds, PAYE formulae, social insurance, levies, benefits and exemptions;
- lawful deductions, pay calendars, leave/bargaining-sector requirements where in scope;
- deterministic rounding and carry-forward rules, retroactive corrections and year-to-date processing;
- report/return/certificate mappings, validation and deadlines;
- source references, amendments, effective and publication dates, legal expert approval and test vectors;
- jurisdiction-specific banking, privacy, records, residency and retention controls.

ZA qualification shall separately test applicable SARS PAYE, UIF, SDL, ETI, tax benefits, directives, year-end certificates and reconciliations, plus Compensation Fund/COIDA employer obligations where applicable. Never imply COIDA is a routine employee deduction. UG qualification shall independently validate URA PAYE and relevant NSSF obligations. Each future market is independently certified.

**No production rule SHALL be generated, updated or published solely by AI.** Regulations may manage official-source evidence and requirements; Pulse may identify possible changes and inconsistencies. Promotion requires named human payroll/tax/legal review, deterministic compiled rule artifact, signed golden fixtures, version pinning, impact analysis, rollback and audit. No unsourced tax rate may enter the production pack.

Qualification is per country + legal regime + affected capability + CDSoftware version + iDempiere digest + PG major + rule-pack hash + effective window. Never use a single global 'Africa compliant' flag.

## 7. Human, financial and privacy safeguards

- Employment records and payroll details are restricted personal information. Enforce least privilege, purpose limitation, field-level classification, encryption and approved access logging; no PII in GitHub fixtures, telemetry, traces, broad finance responses or Pulse embeddings.
- Employee self-service exposes only own authorised records, with independent checks at the resource boundary. HR users, pay-run makers/checkers, approvers, payroll administrators, statutory filers and bank releasers require distinct roles and current grants; high-impact actions require IAM step-up as justified.
- Payroll approval does not override the ERP posting-authority veto (ADR-ERP-022), legal-actor mandates, finance baseline, closed periods or payment controls.
- An approved payroll posts aggregate liabilities and expense by legal entity/period/cost centre, using journal idempotency, balanced debit/credit controls and reconciliation; it SHALL NOT publish individual compensation through finance statements.
- Payslip and tax document retention, lawful deletion, breach evidence and cross-border transfers SHALL follow jurisdiction-specific expert-approved policy and ADR-ERP-017.
- Payroll provider outage, duplicate events, partial statutory submission, partial bank execution, changes to employment state and reversed/corrected runs SHALL have explicit exception and recovery states.

## 8. Database baseline and mandatory upgrade policy

**PostgreSQL 17 is the minimum required major version for new baobab-erp application, iDempiere, test, Codespaces and staging deployment configurations.** The main image tag must be selected through a reviewed pin; production releases SHALL additionally record an immutable digest, exact minor version, extensions and compatible backup/restore proof.

Existing PostgreSQL 16 data directories/volumes are **NOT** PostgreSQL 17 data directories. Never run PostgreSQL 17 against an existing PostgreSQL 16 physical data directory; never use docker compose down -v as an 'upgrade'. The production/staging migration requires:
1. Inventory data volume/version, replicas, extensions, database schemas, custom PG functions, backups, encryption, owners, legal hold and capacity.
2. Freeze writes and perform a verified restorable logical backup (including globals/roles as appropriate) plus storage snapshot; preserve the original cluster.
3. Select and rehearse either logical dump/restore or PostgreSQL-supported pg_upgrade with correct old/new binaries and extension versions; obtain DBA sign-off and point-in-time recovery plan.
4. Verify restored row counts, key sequences, UUIDs, constraints, indexes, extensions, iDempiere AD metadata, Baobab native placement, finance postings, tenant isolation and full ERP regression suites.
5. Record forward-only cutover, downtime/RPO/RTO, backups, WAL/archive continuity, and rollback to intact old cluster under a documented data-reconciliation plan (never naive binary downgrade).
6. Run controlled staging qualification before production with explicit EA-09 authorisation.

Development machines with disposable data MAY reprovision a fresh PG17 volume **only after the operator affirmatively accepts data loss**. CI shall use PostgreSQL 17 consistently; acceptance suites shall verify actual PostgreSQL major 17, not merely an image label.

## 9. Engineering increments and acceptance gates

| Increment | Deliverable | Minimum exit evidence |
| --- | --- | --- |
| BP-00 | This ADR, PG17 config convergence, version-pinned compatibility matrix and safe upgrade runbook | Reviewed source diff, no automatic volume migration, CI configuration checked |
| BP-01 / CD13-01 | CDSoftware origin, licence, release and transitive dependency audit | Immutable manifests/SBOM; exact sources; current maintainer support assessed |
| BP-02 / CD13-02 | CDSoftware 13 compatibility port or justified replacement | Clean Java 17 build; bundle resolve/ACTIVE; unsupported API fixes reviewed |
| BP-03 / CD13-03 | 2Pack/AD/database installation and upgrade tests | Real iDempiere 13 + PostgreSQL 17; idempotent migrations; rollback rehearsal |
| BP-04 / CD13-04 | Canonical workforce and payroll implementation | Shared accepted contract; strict tenancy/security/SoD and E2E synthetic runs |
| BP-05 / ZA | ZA country pack and practitioner validation | Signed statutory golden vectors, full payroll+filing+reversal+accounting reconciliation |
| BP-06 / UG | UG country pack and practitioner validation | Independent URA/NSSF qualification and local filing/retention evidence |
| BP-07 | Multi-tenant commercial service rollout | EA-09, CP bindings, support, incident and licence/commercial approvals |

Failure in BP-01/02 to meet a viable licensing, security, support or compatibility threshold SHALL trigger a documented stop/re-platform decision, not an unsupported production fork. Parallelisation may proceed only where no gate is bypassed.

## 10. Readiness, governance and prohibitions

Before any real pay-run: independently verify employer registrations; assess appointed payroll practitioner; pin statutory pack; prove current employment/legal-actor authority; test maker/checker and bank-release separation; reconcile native ERP postings; validate data protection, incident response and statutory exports; run a supervised parallel payroll; obtain signed operational acceptance and a CP capability-specific activation decision.

Baobab People SHALL NOT:
- introduce a new repository or Engine without an ADR and evidence;
- fork or patch iDempiere core outside ADR-ERP-004's exceptional process;
- claim payroll 13 compatibility from Attendance/other plugin evidence alone;
- use any vendor plugin as public canonical schema or statutorily certified by default;
- store hardcoded country rates, silently overwrite historical calculations or let Pulse/Regulations auto-publish tax rules;
- infer company payroll authorisation from group ownership or IAM authentication alone;
- release money directly from payroll approval or bypass ERP's posting veto;
- turn example providers, CI success, source merge or this ADR into production authority.

## 11. Alternatives considered

**External provider only:** lowest immediate compliance risk, retained for Nabhold continuity, but does not create Baobab People-native commercial IP or configurable African localisation ownership.

**CDSoftware unmodified on iDempiere 13:** rejected pending evidence; public plugin versions do not establish 13 compatibility, reliable dependency support or country statutory support.

**Downgrade iDempiere to 10/12:** rejected; undermines current Baobab standard, extension investment and upgrade/security policy.

**Fork iDempiere core:** rejected by ADR-ERP-004; payroll belongs in governed plugins/services.

**Build entirely from scratch immediately:** deferred; potentially useful if vendor audit fails, but should follow demonstrable reuse and cost analysis.

**Single hardcoded African payroll calculator:** rejected; jurisdictions, employing entities, legal regimes, filing cycles and effective dates differ.

## 12. Consequences and follow-up work

Benefits: reusable enterprise workforce domain, African payroll commercial opportunity, upgradeable extensions, provider neutrality, and a credible ZA→UG foundation.

Costs: a continuing jurisdiction-specific legal/payroll expertise function, GPL and supply-chain management, deterministic statutory testing, sensitive-data operations, supervised migrations, upstream compatibility maintenance, customer support and country-by-country certification.

Follow-ups SHALL be independent PRs/issues where appropriate: Shared People domain census/ADR and contracts; CDSoftware source audit; iDempiere 13 technical qualification; PostgreSQL 16→17 real-data migration rehearsals; ZA and UG statutory packs; Nabhold G07/G08 evidence reconciliation; external-provider contingency and supervised parallel pay runs.

**Decision boundary:** this ADR authorises ERP-local architecture and the controlled investigation/refactoring strategy; it does not self-approve Shared semantics, certify country payroll, activate provider bindings or authorise production employee data.
