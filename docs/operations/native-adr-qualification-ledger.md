# ERP native ADR implementation and qualification ledger

Status: **engineering work in progress; no full native ADR acceptance or protected activation**.
Governing baseline: Accepted ERP ADR-001–020 and 022–023; ADR-021 remains **Proposed**. EA v2.3 / EA-DEV DEV-07/09/11/12/14.
Evidence custody: each gate requires exact source tuple, actual iDempiere 13 + PostgreSQL 17, native JVM/OSGi activation, positive AND negative cases and read-only independent database observations. Source tests are not substituted for business proof.

## Native capability inventory

| ADR | Current implementation foundation | Material native exit criteria still outstanding |
| --- | --- | --- |
| 001 | Pinned iDempiere 13 OSGi and disposable real-JVM Gate D | Independently operated, security-qualified EngineInstance and application services |
| 002 | Authoritative CP assignment parser, ERP placement, tenant map | Real governed ERP assignment, native role/org creation, real two-legal-entity readback |
| 003 | Company/org and placement fences, dedicated clients | Regional/data-residency deployment and second-region isolation evidence |
| 004 | Native context, events, mapping, finance, outbox, integration bundles | Protected OSGi lifecycle, compatibility, rollback/release proof |
| 005 | Restricted app-facing API and native acceptance bridge | Installed, authenticated production-worthy iDempiere REST OSGi routes and integration tests |
| 006 | Canonical outbox/inbox, replay, RabbitMQ, JVM consequence via merged ERP #125 | Original authorised Trade purchase event and live production consumer topology |
| 007 | Canonical/native mapping stores and native reverse context | CP-authorised creation, cross-client binding and lifecycle replay |
| 008 | Finance baseline, native period, live CP veto, ledger insertion fence, N0010 immutable history and N0011 configuration fences | Genuine balanced posted AR/AP/GL and reconciled multi-currency, intercompany, reversal and payment postings |
| 009 | Market/legal placement and finance configuration model | Source-qualified ZA/UG tax and currency packs, statutory testing, period management |
| 010 | Hydra, IAM/CP authority, live native actor/mandate controls | End-user/process/workload least-privilege testing, revocation, cross-client adversarial tests |
| 011 | Same-event exported OTel and independent readback, native attribution | Full BFF-to-native lineage, quantity/amount reconciliation, operational SLO alerting |
| 012 | Native PostgreSQL 17 restore drill, replay and immutable event keys | Real failover, PITR, bounded RPO/RTO, split-brain refusal and multi-company restoration |
| 013 | Pinned image and reproducible native migrations | Rehearsed promotion/rollback/upgrade with signed artifacts and security gate |
| 014 | Projection/master-data mapping and consumer identity | Native governed supplier/customer/product/warehouse create/update and conflict quarantine |
| 015 | Native receipt/order/invoice and purchase-costing accepted test paths | Qualified receiving/lot/quality/valuation/AP chain, supplier three-way match, exceptional and cross-border cases |
| 016 | Protected ERP Sales Order, durable Trade inbox, recovery and outbox | Authenticated buyer-origin event, native invoice/payment accounting, shipment/refund and reconciliation |
| 017 | Provenance, immutable evidence model and N0010 historic financial input fencing | Real private object-store custody, digest, scan/quarantine, retention and legal hold |
| 018 | Canonical event/projection abstractions | Governed financial reporting extracts with independently reconciled trial balances, tenant-filtered analytics, erasure |
| 019 | CP-directed provisioning worker and idempotent commands | Real native onboarding/credential issuance/deactivation, migration, rehome and revocation proof |
| 020 | Readiness evaluation with explicit fail-closed gates | Independent release evidence for each mandatory capability, full multi-company real golden paths |
| 021 | Proposed separate UG/ZA ZuriBeans AD_Client placement | **Governance decision**, verified legal actors, approved finance baseline and CP identifiers; no synthetic activation |
| 022 | Native placement, provenance, class catalogue, PostgreSQL COMMIT fences, N0010 history and N0011 configuration controls | Qualified reversal/bank/cash/manufacturing catalogue extensions only after Shared CP policy revision; do not widen classes locally |
| 023 | Baobab People/CDSoftware candidate on ERP #126 | Licence and compatibility audit, native OSGi/2Pack, statutory ZA/UG parallel payroll, approved posting and HR isolation |

## Gate sequence (no synthetic substitution)

1. **N0 — Native schema and history integrity.** Apply migrations 0001–0026 and N0001–N0012 to clean PostgreSQL 17; run PostgreSQL-backed finance Gate B including authorised posting, forbidden direct-SQL ledger edits/deletes, completed source/line changes, replay, wrong-client, expired decision, unplaced historical isolation. The *same exact versioned image* must complete the actual iDempiere Gate D test.
2. **N1 — Genuine transaction.** Provision legal buyer, seller, membership/site, budget, approved price signer and CP authority through their owning services. Independently read one non-draft Medusa order, seller commitment, buyer spend and the original immutable outbox event at one Trade PostgreSQL XID. Do not count synthetic events.
3. **N2 — Native ERP effect.** Dispatch original event by the existing RabbitMQ publisher; read it from the durable ERP inbox, CP decisions, genuine native C_Order, financial attribution and original unchanged event, including lost-result adoption without duplication.
4. **N3 — Accounting.** Follow native iDempiere source document processing through balanced posted Fact_Acct, AP/AR/stock/cost effects, accounting periods, documented FX and native reversal/credit controls. Compare GL and Trade/evidence totals independently. An ERP Sales Order alone does **not** qualify posting.
5. **N4 — Company and market.** Independently qualify distinct legal AD_Clients/AD_Orgs for UG and ZA only where real legal/Finance approval exists; deny tenant and company crossover, obsolete placement, revoked mandate and invalid accounting period.
6. **N5 — Documents and analytics.** Prove content custody, digest/retention/legal hold and authoritative ledger-derived exports with balance reconciliation; no direct operational database access from Pulse/BI.
7. **N6 — Recovery/operations.** Run real PostgreSQL restore/failover, outbox/inbox replay, correlation/exported-trace join, rematerialisation and independent teardown; record exact run/source hashes.
8. **N7 — Additional native capabilities.** Introduce manufacturing, bank/cash/reconciliation, native reversal, HR/payroll and other uncatalogued document families **only after** Shared erp/v2 operation classes and CP authority are accepted. The present explicit deny-by-name fences must remain intact meanwhile.

## N0010–N0012 safety boundaries

The new forward-only native migrations protect **ledger history** (Fact_Acct UPDATE/DELETE), **completed document source fields and DocStatus**, and **completed commercial/financial line values** from direct SQL tampering for any historically placed AD_Client. Draft line editing remains permitted; legitimate post-completion operational progress counters are not frozen. A placed document may not be deleted, even after a placement closes.

N0012 also refuses TRUNCATE at the PostgreSQL statement boundary on native legal/financial history, document/line/accounting tables and evidentiary records. Row-level DELETE triggers cannot make this guarantee. The refusal is unconditional; governed retention/decommissioning must never silently truncate immutable history.

N0011 independently denies direct SQL changes to unapproved accounting schemas, charts/accounts, tax configurations and bank accounts for historically placed clients, including cross-client reassignment. There is no new CP authority class, and iDempiere system-client configuration remains a separately governed release responsibility.

This is deliberately *not* a replacement for the native OSGi financial veto, CP posting-authority assessment, N0003/N0006 deferrable insertion/completion fences, the legal-actor approval process or a financial reversal operation. There is no arbitrary raw-SQL posting pathway or new authority grant.

**Release posture:** Until N0 is qualified at the PR's final head, this is an integration candidate only. Even after N0, N1–N7 remain independently gated; L4-OPS-01 and protected activation stay BLOCKED.
