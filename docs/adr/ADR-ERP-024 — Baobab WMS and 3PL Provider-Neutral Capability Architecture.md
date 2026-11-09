# ADR-ERP-024 — Baobab WMS and 3PL Provider-Neutral Capability Architecture

**Status:** Proposed for Platform Owner ratification; normative SHALL requirements upon acceptance; **not an implementation or activation approval**  
**Date:** 2026-11-09  
**Repository:** baobab-platform/baobab-erp  
**Capability name:** baobab-wms  
**Decision class:** ERP / Warehouse Execution / Third-Party Logistics / Provider Neutrality / Inventory Custody / Cross-Engine Integration / Quality Assurance  
**Decision owner:** Baobab Platform Enterprise Architecture / Platform Owner  
**Primary consumers:** Nabhold Group operating entities, ZuriBeans, Thamani, independent Baobab tenants, authorised warehouse operators, depositor customers and logistics partners  
**Governing baseline:** Accepted EA v2.3, EA-DEV, ADR-ERP-001–023 (notably 002/003/004/005/006/007/008/010/011/012/014/015/016/017/019/020/021/022); accepted TMS-0001/0002/0017/0020/0021; Shared canonical, context, inventory-ownership, provider, event and cross-engine-reference governance; IAM-0033 and accepted CP/IAM controls  
**Decisions reserved:** Native WMS technology selection; certified default runtime; provider adoption; WMS-specific Shared operation keys and wire schemas; any new native financial-posting classes; vendor licences; regulated market release; staging/production activation  
**Implementation baseline:** Design decision only. No new provider or warehouse capability is certified, no real client is onboarded, and no additional warehouse accounting authority is created by publishing this ADR.

---

## 1. Decision

Baobab SHALL implement **baobab-wms as a first-class, headless, enterprise-grade Warehouse Management System and Third-Party Logistics capability inside baobab-platform/baobab-erp**.

Baobab-wms SHALL be a separately testable, versioned, deployable capability module of the existing Baobab ERP engine and repository. It SHALL **not** be introduced as a new first-class platform repository, independent canonical tenant authority, competing financial ERP, or direct database extension operated by another Baobab engine.

The capability SHALL combine:

1. A Baobab-owned canonical warehouse domain and API/event boundary;
2. An operational execution workflow for authorised warehouse functions;
3. A replaceable **provider-adapter and certification framework** supporting tenants' existing WMS providers, outsourced 3PL operators, Baobab-operated warehouse execution, and selected native extensions;
4. Strict separation of physical custody, operational warehouse observations, legal inventory ownership, stock reservation, inventory accounting, transport execution and billing;
5. Explicit Control Plane/IAM legal-actor, entitlement, tenant, provider, warehouse, environment, isolation, scope and revocation enforcement;
6. Internationally interoperable identification, tracking, EDI, auditability and quality-assurance practices, activated per certified capability; and
7. PostgreSQL 17-backed canonical operational state, durable event custody, reconciliation, independent evidence and service-level qualification where Baobab owns the corresponding execution component.

**The technology used to execute Baobab-managed WMS operations is deliberately undecided.** A dedicated follow-up architecture and engineering assessment SHALL compare an iDempiere-native/custom extension against suitable independently deployable open-source warehouse runtimes. No external product, native engine or architectural option shall be silently declared the default before that selection and a witnessed certification. Keeping the capability within baobab-erp does not require every WMS worker to execute inside the iDempiere JVM.

**Quality rule:** Baobab SHALL establish measured functional, security, reliability, operational and interoperability parity with leading relevant international warehouse/3PL systems for every capability it claims to offer, and SHALL seek demonstrable superiority where it can be measured. Marketing claims of parity or superiority without representative, reproducible comparative evidence are PROHIBITED.

## 2. Context and problem

Accepted ADR-ERP-015 recognises iDempiere as authoritative for financially consequential warehouse inventory and its valuation, while acknowledging that an operational warehouse or 3PL provider may own physical execution and observation. ADR-ERP-014 requires explicit master-data and attribute authority. TMS-0017 separates warehouse bin and stock handling from transport custody; TMS-0020/0021 already establish provider-neutral transport execution under CP governance.

These decisions require a coherent WMS boundary, but do not themselves deliver a full enterprise warehouse/3PL runtime. Without one, the platform risks presenting iDempiere warehouse configuration, Trade availability, TMS carrier status and a third-party warehouse's operational records as if they were the same stock truth.

Baobab also serves distinct business models: owner-operated storage, outsourced fulfilment, a warehouse operator holding another company's goods, multiple depositor customers in one facility, group subsidiaries with separate legal ownership, and independent external tenants retaining preferred incumbent systems. Any architecture that assumes one tenant equals one warehouse, owner, operator, market, provider or ledger is unacceptable.

The objective is not a cosmetic inventory dashboard. It is verified execution of complex physical work with lawful financial consequences, customer isolation, real contractual 3PL services and high-confidence reconciliation.

## 3. Normative interpretation

**SHALL/MUST** indicates a mandatory architectural requirement; **SHOULD** requires recorded rationale for deviation; **MAY** is permitted subject to other controls; **PROHIBITED** is not an ordinary configuration option.

Architecture acceptance, source implementation, external certification and release are separate states. An accepted ADR or passing unit test SHALL NOT itself grant runtime, legal, security, customs, provider or financial authority.

## 4. Repository placement and bounded architecture

The authoritative source SHALL live under **baobab-platform/baobab-erp**. Illustrative module boundaries, subject to the repository's normal package approval, are:

- **modules/wms/domain/** — canonical facility, handling-unit, custody, task, lot, inventory-observation and 3PL-service models.
- **modules/wms/application/** — command/query handlers, decisions, workflow state machines, transactional outbox, reconciliation and exception handling.
- **modules/wms/providers/** — provider-neutral ports, scoped adapter bindings, certification vectors and anti-corruption mappings.
- **modules/wms/integration/** — approved ERP, Trade, TMS, Trade Docs, Regulations, CP/IAM integration and external partner contracts.
- **idempiere/extensions/org.nabhold.baobab.erp.wms/** — native OSGi integration only if justified and qualified; it SHALL respect the existing iDempiere extension policy and SHALL NOT fork the upstream code.
- **db/migrations/** — versioned Baobab-owned PostgreSQL 17 persistence, distinct from native iDempiere ownership.
- **tests/wms/** — contract, safety, multi-company, provider, warehouse process, load, replay and real-native acceptance.

These are candidate paths, not evidence they already exist. The canonical WMS service MAY run as an internal process or separately deployed service maintained within baobab-erp, when deployment isolation or availability requires it. It SHALL retain the same ERP capability ownership, CI/release authority and CP registration; it SHALL NOT become an undeclared external platform engine.

A certified external WMS has its own native data and execution runtime. Baobab owns only its canonical references, approved operations, observations, contracts and reconciliation. External provider tables SHALL NOT become shared Baobab database tables.

## 5. Non-negotiable invariants

- **WMS-INV-01 — Ownership is not custody.** Physical storage, handling or carrier handoff SHALL never imply title transfer, inventory asset recognition or right to dispose of goods.
- **WMS-INV-02 — Physical observation is not posted accounting.** WMS work completion SHALL not set native ERP posting status, directly write Fact_Acct, alter M_Cost, invent a financial movement or bypass an unqualified native document family.
- **WMS-INV-03 — Customer is not legal owner.** Warehouse operator, service customer/depositor, inventory-owning legal entity, contractual seller and physical custodian SHALL remain separately represented.
- **WMS-INV-04 — No implied group access.** Common shareholders, parent organisations, warehouse location or tenant membership SHALL not grant access to another company's stock, orders, service rates, cost or records.
- **WMS-INV-05 — One accountable physical execution authority per bounded operation.** When an incumbent provider executes a task, Baobab SHALL record that provider's verifiable observation and shall not fabricate a parallel physical completion.
- **WMS-INV-06 — No invented availability.** Unknown, contested, quarantined, damaged, held, unreconciled or stale stock SHALL not become sellable merely because a WMS, ERP or Trade response is missing.
- **WMS-INV-07 — No silent provider failover.** A started/committed operation SHALL retain a pinned provider binding and generation. Timeout or lost acknowledgement is UNKNOWN until independently reconciled; never automatically duplicated at another warehouse/provider.
- **WMS-INV-08 — Contract and event provenance.** Every consequential fact retains canonical identity, original source, event and business timestamps, actor, provider reference, legal/entity/facility scope, policy version and correlation.
- **WMS-INV-09 — Idempotent business effect.** Redelivery or retry SHALL never duplicate receiving, dispatch, billing, stock correction or financial consequences.
- **WMS-INV-10 — No unsupported certification.** A provider's claimed capability SHALL remain unavailable until its actual operation, negative cases, isolation and recovery behaviour are certified.
- **WMS-INV-11 — No financial backdoor.** Native posting, valuation, reconciliation and reversal remain subject to accepted ERP-008/022 controls and separately authorised Shared/CP operations.
- **WMS-INV-12 — Local correctness over superficial availability.** On authority, provenance, quantity, ownership, safety or release uncertainty, the affected irreversible transition SHALL fail closed or enter a visible pending/exception state.

## 6. System-of-record and responsibility matrix

| Domain or fact | Authoritative owner | Baobab-wms rights and constraints |
| --- | --- | --- |
| Tenant, Organisation, LegalEntity, Market, subscription, rights and capability bindings | CP, IAM and governed Shared contracts | Enforce exact scoped authority; no shadow tenant system |
| Canonical product/party/warehouse identifiers and mappings | Designated Shared/domain owners under ERP-007/014 | Maintain typed external references; no name-based joins |
| Facility, bin, work order, handling unit and observed physical state | Certified physical warehouse executor; WMS canonical boundary | Execute where delegated; preserve observations when outsourced |
| Receipt, putaway, pick, pack, count, damage and quality observation | Certified WMS/3PL execution provider | Distinguish observed, acknowledged, disputed and ERP-booked |
| Inventory ownership and intercompany title | Approved legal/ERP workflow, Shared ownership contract | Reference; do not infer from facility or scan |
| Physically and financially recognised ERP stock; costing, GL, AP, AR | iDempiere under baobab-erp | Request authorised documents; verify actual durable posting |
| Commerce order, reservations, sellable allocation | Baobab Trade / Medusa | Consume commitments; never overwrite Trade reservations |
| LogisticsShipment, carrier plans, booking and transport custody | Baobab TMS | Send/receive bounded handoff evidence, not carrier commands |
| Documents, regulatory releases, quality certifications | Trade Docs, Regulations and relevant real authorities | Reference pinned decisions and verified document versions |
| WMS services performed and chargeable activity observations | WMS/qualified 3PL operator | Supply defensible billing facts; never post AR directly |
| 3PL customer invoice, charge accounting and payment settlement | iDempiere ERP, actual approved payment authorities | Submit reconciled billing instructions; no payment execution |

A projection is not automatically an authority. Any mismatch among physical observation, financial stock, commercial reservation and transport custody SHALL be visible as a reconciliation exception rather than silently overwritten.

## 7. Canonical WMS domain

The following are proposed **ERP-owned warehouse-domain objects**, not newly registered Shared contracts:

1. **WarehouseFacility** — facility identity, address, country, time zone, operator, storage capabilities, safety/regulatory constraints, integration references and permitted customers.
2. **WarehouseZone / BinLocator / CapacityUnit** — physical zones, bin layout, allowed stock types, temperature/hazard rules and spatial or weight/volume capacity.
3. **WarehouseCustomerAccount / WarehouseServiceAgreement** — operator–customer contractual relationship, effective service and rate entitlements, depositors, SLAs, liability, billing and permitted warehouse actions.
4. **InventoryOwnerAccount** — legal owning party, warehouse operator, custody model, ERP client mapping, segregation class and title/consignment status. It is not a new CP LegalEntity.
5. **ProductWarehouseProfile** — canonical product reference and warehouse-specific dimensions, UOM conversions, pack configuration, handling rules, hazard class, shelf-life and quality gates.
6. **HandlingUnit** — pallet/carton/container/tote/case with canonical identity, optional GS1 SSCC, parent-child aggregation, quantities, seals and custody evidence.
7. **StockLot / Serial / BatchGenealogy** — traceable manufacturing/production and receipt references, supplier lot, expiry, quality and recall status; one generic batch field SHALL NOT erase product-specific traceability requirements.
8. **WarehouseInventoryObservation** — observed quantity by owner, facility, bin, product, lot, condition and time; independent of ERP-booked quantity and Trade reservation.
9. **InboundNotice / ReceiptTask / Inspection / PutawayTask** — scheduled arrival, independently counted quantity, discrepancy, QC decision, segregation and placement.
10. **OutboundInstruction / Allocation / PickTask / PackTask / DispatchConfirmation** — approved release instruction, assignment, scan-confirmed execution, handling-unit packing and outbound custody transfer.
11. **CountPlan / CountObservation / ReconciliationCase / AdjustmentRequest** — blind/cycle counts, investigation, approved correction request and native ERP posting result; a count does not itself post a write-off.
12. **CustodyHandoff / WarehouseException / EvidenceReference** — signed or attributable transfers, refused/partial/contested handoffs, immutable observations and evidence.
13. **ChargeableWarehouseActivity / BillingStatement / InvoiceReference** — verified services, dimensions/UOM, effective rate card, price exception, invoicing eligibility and ERP accounting trace.
14. **NativeWarehouseProviderBinding / ExternalWarehouseReference** — tenant-scoped provider mapping and execution certification; external identifiers SHALL NOT be exposed as canonical identifiers.

Every core aggregate SHALL have explicit tenant, operating Organisation, operator legal entity, inventory owner, customer scope, facility, immutable ID, revision, effective time, observed time, source, and applicable market/isolation when those dimensions apply. An unresolvable or ambiguous identifier SHALL fail closed.

## 8. Physical execution capabilities

Baobab-wms SHALL be designed for the following internationally competitive capability groups. The selected executor may implement only the operations it proves.

**Inbound:** ASN/pre-advice, appointment and dock assignment, supplier/customer inbound identity, receiving, over/short receipt, damaged/contaminated exceptions, blind count, serial/lot capture, condition, inspection, quarantine, putaway, cross-docking and supplier return proposals.

**Storage and control:** mapped capacity, multi-zone/bin execution, license plates/handling units, directed and confirmed putaway, replenishment, relocation, directed consolidation, stock aging, cycle count and full count, discrepancy/correction proposals, block/recall/hold, ownership segregation and container/pallet hierarchy.

**Outbound:** release eligibility, wave/waveless and order-specific allocation strategies, FIFO/FEFO and other versioned configurable methods, picking, packing, consolidation, weighing, labelling, cartonisation/handling-unit association, load staging, shipping confirmation, shortage/substitution approval, reverse picking and recovery. Strategy selection SHALL respect product, contract, expiry, lot, stock owner and market restrictions rather than blindly optimising distance.

**3PL and multi-customer operations:** multiple depositor customers, separate owners in one physical facility, client-specific workflows, outsourced inventory visibility, storage fees, pallet/day or position/day charges, receiving, picking, packing, handling and approved accessorial billing, SLA measurement, disputes, correction and independently invoiced warehouse services.

**Traceability and regulated goods:** batch genealogy, quality inspections, holds, recalls, temperature or humidity telemetry, seals, dangerous-goods and bonded-warehouse restrictions when qualified. No pharma/food/chemical or bonded capability is implied by a generic product field.

**Extended operations:** yard/dock scheduling, labour measurement, equipment/task assignment, mobile/RF scanning, offline operations and mechanisation adapters. Automation/robotics/voice-pick shall be optional certified capability profiles, not obligatory dependencies.

A feature SHALL NOT be advertised as present because its domain entity or API placeholder exists. It requires a complete operational test, documented supported conditions and independently verified persistence.

## 9. Provider neutrality and tenant choice

The choice to keep an existing warehouse provider SHALL be respected subject to certification, legal entitlement, contractual access and acceptable safety/security controls. Baobab SHALL not force a migration merely to sell the Baobab-native WMS option.

A native execution binding SHALL contain, at minimum:

- tenant, operating Organisation, warehouse operator and inventory-owning legal entity context;
- warehouse facility, market/jurisdiction and customer agreement scope;
- CP capability binding, approved isolation/residency profile and environment;
- provider kind, verified immutable release/version, certified operations and modes;
- provider resource IDs, scope-specific credential **references** (never secrets);
- health/verification times, revocation/lease and generation/fencing token;
- provenance, terms/licence status, policy and certification evidence;
- owner of native operational data, recovery support and exit/export capability.

Selection SHALL be deterministic and **per operation, facility, customer/owner scope and capability**, not an unconditional one-provider-per-tenant setting. Prefer the tenant's verified incumbent binding; otherwise offer a separately qualified Baobab-managed native option. If no option qualifies, return **NO_CERTIFIED_PROVIDER**; do not choose an untested fallback.

No committed work order may switch execution provider merely because the selected provider times out. Provider suspension requires fencing new commands, preserving history, reconciled in-flight ownership and an approved cutover plan. A provider's local user, account, organisation or warehouse is not a Baobab Tenant, Principal, LegalEntity or financial AD_Client.

**Native technology selection is postponed.** It SHALL be the subject of a later independent alternatives assessment with capability-fit, licence, security, maintainability, upgrade, total-cost, iDempiere 13 compatibility, PostgreSQL 17 compatibility, runtime isolation and operational acceptance evidence. This ADR selects the **portable boundary**, not the implementation product.

## 10. Three-party legal and 3PL accounting model

Every warehouse service SHALL separately identify:

1. **Warehouse operator:** entity legally providing handling/storage or controlling the site.
2. **Inventory owner / entitled depositor:** entity with the legally and commercially established stock ownership or consignment entitlement.
3. **Service customer:** entity that contracts for and pays the operator's services.

A customer may be an external Baobab tenant or a legal entity under another tenant. A group relationship creates no automatic contract, data sharing, tax, billing or stock access. One physical facility may hold goods of multiple unrelated customers and owners. Physical co-location SHALL NEVER merge their stock books or entitlement.

A WMS service agreement SHALL declare approved storage/handling methods, service rates, effective dates, billing currency, tax jurisdiction and approver, minimums, exceptions, liability, insurance evidence and permitted access. Billing quantities SHALL be derived from durable source activity or independently validated inventory positions, not unaudited provider estimates.

A **WMS billable event is not a financial invoice**. The approved iDempiere company of the operator alone recognises AR/tax/revenue through authorised native posting. The depositor's inventory never becomes operator-owned stock merely because the operator invoices storage charges.

Cross-legal-entity stock transfer requires separately authorised ERP/legal transfer or consignment workflows. WMS may report where the goods are, but must not assert when legal title passed.

## 11. ERP-native financial and inventory boundaries

iDempiere SHALL remain authoritative for legally and financially recognised stock, procurement documents, material receipts/issues, cost details, valuation, GL/AP/AR and accepted corrective accounting.

- WMS physical receipts, adjustments and shipments are **observations/requests**, not unqualified native postings.
- A native ERP document operation SHALL include resolved CP authority, native company/org placement, product/warehouse mapping, accounting date, cost/tax configuration and the applicable posting catalogue.
- Existing ERP-022 guards on placed clients, derived costing, matching and attribution SHALL remain intact; WMS must not bypass them through SQL, a new admin endpoint or a privileged worker.
- Native operations currently excluded from the accepted Shared ERP posting catalogue SHALL remain **BLOCKED** until a separate approved Shared/CP class and genuine PostgreSQL/JVM evidence exist.
- Financial posting failure SHALL not erase a valid physical observation. It SHALL leave a clearly labelled **PHYSICAL_OBSERVED / ERP_PENDING / ERP_REFUSED / RECONCILED** state, with policy-based release holds.
- A correct ERP book entry SHALL be confirmed through independent readback of native source document, company, quantity, posting status, ledger/valuation evidence and canonical mapping; a HTTP success response alone is insufficient.
- WMS will not implement an alternative general ledger, cost valuation calculation, tax engine or cross-client consolidation.

Known outstanding ERP accounting qualification work, including the separate native finance integrity draft, remains independently gated; WMS development SHALL not be used to mark that work accepted.

## 12. Inventory semantics and reconciliation

Baobab SHALL expose distinct, unambiguous quantities:

- **physical_observed:** last verified WMS count by owner/facility/bin/lot/condition;
- **erp_booked:** durable native ERP inventory balance within its own legal client's accounting rules;
- **erp_allocated:** ERP-side documented allocation or reservation;
- **trade_reserved:** commerce-local commitment from Baobab Trade;
- **quality_held / blocked / damaged / in_transit:** operational restrictions and states with provenance;
- **sellable_projection:** explicitly calculated and versioned Trade-facing eligibility under approved reservation/staleness policy.

These values need not coincide at every instant. No universal equation of "WMS on hand = ERP on hand = Trade available" is valid. A reconciliation policy SHALL compare equivalent scope, ownership, UOM, lot, cutoff time, period and lifecycle before classifying variance.

Reconciliation SHALL support physical-to-ERP, WMS-to-provider, ERP-to-Trade, handoff-to-TMS, chargeable-service-to-invoice and restored-state-to-before-failure comparisons. Variances SHALL create durable exception records with severity, owner, evidence, resolution authority and disposition. Critical unrecognised variance SHALL block affected sale/dispatch and adjustment paths.

Where goods are on consignment or held for third parties, WMS custody balances SHALL not be mistaken for asset balances on the warehouse operator's books. Inventory ownership cross-engine semantics SHALL reconcile with Shared **inventory-ownership/v1**, not overwrite it or silently re-issue ownership events.

## 13. Cross-engine integration

**Baobab Trade:** ingest approved fulfilment requests, item/lot/quantity constraints and reservations; publish picking, packing, dispatch and verified shortfall facts. Do not create or override commerce orders, prices or buyer spending commitments.

**Baobab TMS:** exchange warehouse ready-to-load, actual pickup/handoff, signed acknowledgement, handling-unit/consignment references, seal/condition data and contested/partial custody transitions. TMS owns carrier route, transport plan, booking and delivery movement. WMS owns the physical warehouse execution side of a handoff.

**Trade Docs / Regulations:** attach pinned document versions and recorded source decisions; bonded release, restricted cargo, export/import and product-specific requirements block the applicable workflow until satisfied. WMS must not infer regulatory clearance from a customs status label.

**CP/IAM:** validate legal actors, provider scope, facility/customer authority, credentials, revocation, admission, cross-tenant relationships and environment/isolation. WMS business roles SHALL be object- and action-specific. A user allowed to pick one client's items is not thereby entitled to that client's costs, service rates or other owners' stock.

**ERP native integration:** use approved supported application service/OSGi interfaces. Native transaction identifiers remain private references. Durable source-event and document mapping SHALL survive replay, migration and provider substitution.

**Pulse and analytics:** consume governed projections/exports only. Analytics must not become a posting or operational inventory authority.

No engine SHALL bypass its neighbour's API/event boundary with direct SQL, a shared database transaction or an unregistered event. Concurrency shall be handled through durable independent transactions, explicit states and reconciliation.

## 14. International identification, visibility and interoperability

Baobab SHALL design for international adoption while respecting that not all warehouse customers have GS1-issued identifiers or EDI infrastructure.

- **GS1:** support verified GTIN, GLN, SSCC, applicable GS1 Application Identifiers, machine-readable labels, logistics-unit nesting and correct validation under the applicable GS1 General Specifications. Never invent GS1 identifiers, prefixes or rights of issuance.
- **GS1 EPCIS / CBV:** provide a versioned mapping to **EPCIS 2.0.1 and CBV 2.0** for applicable capture/query and WHAT/WHEN/WHERE/WHY visibility facts, including aggregation, transformation/transaction relationships and sensor observations where relevant. Native Baobab event contracts remain Shared-governed; EPCIS is an interoperable projection/interface, not a duplicate operational source.
- **EDI:** adapter profiles SHOULD support versioned partner exchange, as required, including ANSI ASC X12 **940, 943, 944, 945, 947** and appropriate inventory interchange; UN/EDIFACT delivery, receiving and inventory messages where specified by partner agreements. No blanket claim of compliance with every EDI release or partner implementation guide is permitted.
- **REST/OpenAPI and AsyncAPI:** publish canonical authenticated HTTP commands/queries and durable event specifications with schema compatibility and replay vectors. Provider callbacks must be authenticated, scoped, deduplicated and quarantined on structural or semantic mismatch.
- **UOM and location:** implement exact-decimal quantities, explicit measurement precision and governed conversions; represent location coordinates, time zones, country and market independently. No implicit kilogram-versus-piece conversion.
- **Traceability:** scans, temperature/condition evidence and lot genealogy retain source trust and independent validation. A scan is proof of a recorded observation, not automatically legal acceptance.

International identifiers and message formats are implemented as **certified capabilities**, never mandatory obligations imposed on every tenant irrespective of their contracts and operating conditions.

## 15. Security, isolation, privacy and legal assurance

- **Zero implicit authority:** IAM authenticates; CP supplies authoritative tenant/legal/relationship and permission context; WMS enforces every command, query, record and emitted event against the actual object and operating scope.
- **Separation of duties:** receiving approval, stock correction, customer price maintenance, write-off, release of quarantined stock, override of a warehouse stop, service rate changes and ERP posting approval SHALL be appropriately segregated.
- **Provider boundary:** each external/native WMS receives scoped workload identity, minimum API permissions, expiry/revocation, credential rotation and constrained callbacks. No general ERP database credentials are given to a WMS provider.
- **Isolation proof:** facility and warehouse-customer partitions, owner segregations, users, worker queues, caches, exports, telemetry, object storage, backups and provider-native organisation routing SHALL all pass cross-tenant negative tests. Tenant columns alone do not prove isolation.
- **Supply-chain security:** physical access/dispatch control, seal anomalies, unauthorised inventory removal, tampering, fraudulent counts, supplier/counterparty identity and verified exception escalation SHALL be designed into high-risk warehouse flows.
- **Privacy:** personal information, driver/worker identities, vehicle location, customer rates and sensitive warehouse positions SHALL be classified, minimised, access-controlled, retained and exported under documented legal basis and residency rules.
- **Data integrity:** original scans/messages and adjudication records shall be immutable or append-only where legally/accountingly relevant. Corrections append a linked correction, not a rewrite of history.
- **Regulated operations:** food-safety, pharmacological, cold-chain, dangerous-goods, customs-bonded and other regulated profiles require separate domain/legal evaluation and witnessed qualification; no generic software installation constitutes compliance.

Open APIs SHALL be tested against OWASP API Security risks, including object-level and property-level authorization failures. Actual conformity with ISO management system standards requires organisational controls and, where claimed, external certification, not merely programmatic test success.

## 16. Reliability, distributed execution and failure semantics

- PostgreSQL 17 SHALL persist Baobab-owned canonical warehouse state with migrations, transactional constraints, audit history and an outbox for committed business facts.
- At-least-once messaging with inbox deduplication and idempotent *business effects* SHALL be the default. Exactly-once broker delivery SHALL NOT be assumed.
- Every command must include stable idempotency/operation ID, version or optimistic precondition, legal/facility context and provider binding generation. Native acknowledgements and external references SHALL be durable.
- Out-of-order, delayed, duplicated, contradictory and lost-result events SHALL be recognised as normal distributed failure modes, not silently "fixed" by latest-message-wins on material stock.
- Irreversible work SHALL use business-specific compensation with new evidence and authority; no rollback of a physical shipment or a legal document is invented merely because an API returns an error.
- Offline mobile capture MAY be supported with signed/bounded sessions, local safe-storage protections, sequence numbers, conflict detection and a *pending* state until re-admitted and reconciled. Offline clients SHALL not independently approve financial write-offs, provider changes or legal releases.
- Recovery SHALL include restored PostgreSQL/worker/provider snapshots, operation and provider-binding continuity, native ERP readback, replay with no double effects, and disposal of test resources. RPO/RTO targets require tested operator runbooks.

## 17. International quality and operational excellence

The quality baseline SHALL reference the current applicable editions of:

- **ISO 9001:2026** — quality management process, customer requirements, control of nonconformity, corrective action and continual improvement.
- **ISO/IEC 27001:2022** — information security management controls and risk treatment.
- **ISO 28000:2022** — security management, including supply-chain risks.
- **ISO 22301:2019** and applicable amendments — continuity management and tested recovery.
- **ISO 45001:2018** — relevant occupational safety management alignment for warehouse and equipment workflows.
- **GS1 General Specifications 26.0.0, EPCIS 2.0.1 and CBV 2.0** — data identification, traceability and event interoperability.
- **OWASP API Security Top 10** — application and integration threat modelling; applicable supply-chain and industry requirements remain separately governed.

Baobab SHALL not claim that its software or any warehouse operator is ISO-certified, GS1-certified, customs-bonded, GDP-compliant or otherwise accredited unless independently issued evidence applies to that precise legal operation/scope.

Quality objectives SHALL be translated into controlled engineering fitness functions, representative workload tests, defect prevention, change traceability, root-cause review and actual operator drills. A product qualifies as internationally competitive only with independent scenario coverage and reproducible benchmark comparators appropriate to its certified scope.

### 17.1 Proposed non-universal engineering budgets

These are **initial design targets for qualification planning**, not claims of existing performance or universal contractual SLAs. A production SLO requires an approved representative load model (concurrent users, scan rate, warehouse layout, provider RTT, database sizing, environmental conditions and outage assumptions).

| Indicator | Proposed initial benchmark / mandatory principle |
| --- | --- |
| Wrong tenant/owner/customer read or write | **Zero permitted**; any proven violation is release blocking |
| Unauthorised material stock or financial transition | **Zero permitted**; every attempt must be refused and audited |
| Duplicate business effect after retry/replay | **Zero permitted** in witnessed scenarios |
| Local scan command acknowledgement | Target p95 ≤ 250 ms on explicitly specified supported devices and LAN; external provider/network latency reported separately |
| Headless WMS business query | Target p95 ≤ 300 ms at agreed load and hot/cold cache profiles; p99 and saturation must also be published |
| Successful local event capture into durable outbox | Atomic with the relevant business state transition; no acknowledged event loss |
| Provider acceptance/notification | Report actual observed latency, stale/unknown backlog and per-provider SLO; no fictitious instant confirmation |
| Production service availability target | Design toward ≥ 99.95% for certified service boundary; recovery, exclusions and measurement window must be contractually defined |
| Physical count accuracy | Measure variance by facility/owner/product and UOM with independently audited cycles; target ≥ 99.9% where justified, without suppressing actual discrepancies |
| Stock traceability/recall | Deterministically locate affected lots, handling units, owners and handoffs in verified, time-bounded scenarios |
| Recovery | Document and rehearse service-specific RPO/RTO and cross-provider reconciliation; no untested "high availability" badge |
| Accessibility and UX | WCAG 2.2 AA for applicable user interfaces; mobile/scan ergonomics under actual warehouse constraints |

These are programme baselines to refine through field trials and benchmark evidence. No business-safety guard may be relaxed to achieve a throughput or latency score.

## 18. Release, benchmarking and acceptance gates

The programme SHALL distinguish architectural approval from engineering completion and provider certification.

| Gate | Required independent proof |
| --- | --- |
| **WMS-00 Architecture** | Approved ADR, ownership/authority matrix, Shared changes, CP/IAM entitlement and identified legal/service relationships |
| **WMS-01 Native options research** | Independent iDempiere extension versus open-source runtime fit-gap, licence, security, ecosystem, maintenance, upgrades and witnessed prototype; **no predetermined winner** |
| **WMS-02 Canonical domain and identity** | PostgreSQL 17 migrations; owner/operator/customer/facility semantics; correct UOM/lot/SSCC and ambiguous/expired mapping refusals |
| **WMS-03 Provider neutrality** | At least two interchangeably exercised provider adapters (one may be a controlled test provider), incumbent-preservation case, scoped credentials, revocation, binding pinning, failover UNKNOWN and migration/export |
| **WMS-04 Inbound and storage** | ASN → arrival → partial/damaged receipt → QC hold → bin putaway; independent stock/handling-unit readback and wrong-owner negatives |
| **WMS-05 Outbound and returns** | Authorised pick → pack → load/handoff; shortage, quarantine, FEFO/lot, cancel, returns, disputed handoff and no duplicate dispatch |
| **WMS-06 Inventory reconciliation** | Independently compare provider observations, warehouse ledger, native ERP posting, Trade reservation and physical-count variance; block unsafe availability |
| **WMS-07 Multi-customer 3PL** | One warehouse operator, two unrelated inventory owners/customer accounts, separate rates, stock access and invoice liabilities; no group inheritance |
| **WMS-08 ERP financial consequence** | Real iDempiere 13/PostgreSQL 17 native document, correct AD_Client/AD_Org, legal-actor CP authority, posting/costing where catalogued, negative veto, replay and independent readback |
| **WMS-09 TMS/Trade/Docs** | Same identified handling unit through pick, custody handoff, logistics consignment and Trade order; source event/DocumentVersion provenance and mismatch negatives |
| **WMS-10 International interoperability** | GS1 validation, EPCIS 2.0.1 roundtrip, partner-scoped X12/EDIFACT contract vectors where offered and invalid-message quarantine |
| **WMS-11 Nonfunctional/security** | Concurrency, performance budgets, lost messages, restart, isolation across caches/workers/backups, secrets, SBOM, SAST/DAST, resilience, WCAG 2.2 AA and privacy |
| **WMS-12 Operations and recovery** | Real restored PostgreSQL, replay, provider reconciliation, feature suspension, runbooks, monitoring, rollback of code without fictitious physical rollback, independently verified cleanup |

The evidence bundle SHALL bind exact Baobab and selected-provider commit SHAs, image digests, contract and policy versions, native iDempiere release, PostgreSQL version, CP/IAM source, commands/tests, independent witnesses, both positive and negative outcomes and known limitations.

Mandatory business scenarios SHALL include: a customer receiving its own stock; an operator holding another company's goods; two unrelated depositors in the same bin/facility segregation regime; a UG→ZA traceable commodities corridor; regulated/quality-held stock; partial/damaged receipt; duplicated provider webhooks; disallowed lot substitution; provider revocation in flight; lost ERP posting result; out-of-order TMS handoff; backdated adjustment request; and a successfully recovered provider outage without duplicated financial effect.

No test harness, synthetic credential or generated account may be represented as actual legal incorporation, a real carrier/warehouse provider commitment, real external payment, licensed regulated operation, protected environment or third-party certification.

## 19. Implementation waves and cross-repository dependencies

**Wave A — Normative specification:** accept this ADR and reconcile explicit amendments with ERP-014/015, TMS-0017/0020/0021, Shared warehouse and inventory-ownership contracts, CP provider/isolation/binding controls and IAM. Publish a capability/operation catalogue proposal; do not activate unapproved keys.

**Wave B — Technology-neutral kernel:** implement WMS domain, PostgreSQL schema, canonical API/event surface, state machine, immutable source observations, operational role matrix and integration test harness inside baobab-erp.

**Wave C — Native-executor research and bounded prototype:** evaluate the iDempiere-native extension option and competing open-source warehouse runtime options with the same feature and isolation test suite; make a separate recorded decision choosing the initial certified Baobab-managed execution solution. Do not let the first prototype dictate Shared contracts.

**Wave D — Real inbound/outbound and incumbent adapter:** qualify at least one real warehouse execution path and a provider-neutral alternative; prove tenant retaining an incumbent without replacing its system of record.

**Wave E — Three-party 3PL operations:** implement multi-owner stock custody, client-specific permissions, rate agreement, handling-unit/service evidence, financial billing and disallowed cross-client behaviour.

**Wave F — Connected operational/financial acceptance:** qualify real Trade/ERP/TMS/Docs flows, native postings where approved, entire trace and replay, internationally relevant interchange, restore and measurable benchmark profile. Protected staging/production gates remain separate.

Dependent Shared, CP, IAM, TMS, Trade and Trade Docs changes SHALL be implemented under their respective owning repositories/ADRs. Hosting WMS within baobab-erp does **not** permit ERP to rewrite their canonical contracts or legal authority.

## 20. Migration, portability and exit

Baobab SHALL enable phased onboarding with a tenant retaining its existing provider, using bounded import and read-only shadow projections before executing warehouse commands. Provider migration SHALL include inventory owner reconciliation, handling-unit and lot lineage, in-flight task fencing, credential revocation, explicit unsettled service fees, historical evidence retention and signed approval of the cutover window.

Provider export SHALL be available in documented canonical forms, subject to contract, privacy and legal retention. Changing vendor does not change historical business identities, erase external references, reassign a legal inventory owner or allow duplicate receiving/dispatch. A platform customer SHALL not be technologically locked in merely because an adapter was convenient.

## 21. Rejected alternatives and shortcuts

- A new **independent Baobab WMS platform repository/engine**: rejected for this decision. The WMS capability belongs under baobab-erp, even when its execution process or external provider is independently deployed.
- A single mandatory warehouse vendor for all tenants: rejected; provider eligibility and tenant choice are governed.
- Treating a warehouse provider's customer/organisation identity as a Baobab Tenant or LegalEntity: rejected.
- Treating WMS on-hand or provider inventory as iDempiere financially posted inventory: rejected.
- Treating a TMS delivery milestone as a bin transaction or a warehouse scan as legal title transfer: rejected.
- Using direct native database updates or bypassing ERP posting controls to speed fulfilment: rejected.
- Duplicating Trade reservations as WMS reservations with no binding or reconciliation: rejected.
- Choosing a provider based on marketing capabilities, README screenshots or successful HTTP ping: rejected.
- Declaring a green unit suite, architecture document, performance number or API response sufficient for international/production certification: rejected.
- Putting ERP posting, payment execution, carrier booking and customs release under one overprivileged WMS role: rejected.
- Rewriting historical custody, accounting, provider assertions or financial facts after operational disputes: rejected.

## 22. Consequences and risks

**Positive:** Baobab gains an integrated ERP-owned warehouse capability, international interoperability posture, meaningful tenant/provider choice, reusable 3PL service models, strong physical/financial boundaries, reduced duplicated integration logic and measurable enterprise quality.

**Costs:** additional canonical event and reconciliation work, provider-adapter certification, warehouse mobility and operational hardware testing, complex owner/operator/customer permissions, external contract and licence reviews, and increased observability/DR requirements.

**Risks and mitigations:** duplicate authority is addressed by the matrix and independent reconciliation; vendor lock-in by stable contracts and exit evidence; financial divergence by native posting vetoes and comparison; multi-customer data leakage by object-level and worker/backup isolation; unsafe provider failover by pinned binding/unknown-result adoption; regulatory overclaiming by per-operation certification and legal review.

The choice to remain within baobab-erp is a governance and repository ownership decision. It SHALL NOT force inappropriate synchronous coupling or make a warehouse handheld unavailable whenever an accounting API is temporarily unhealthy; safe work states and deferred native effects must be explicitly engineered and tested.

## 23. Definition of done — binding acceptance criteria

This ADR's implementation SHALL be considered **engineering-complete** only after:

1. Accepted ownership, legal/custody and provider-neutrality contracts exist and are enforced;
2. The selected Baobab-managed runtime has passed separate technology-selection and operation-certification gates;
3. Tenant/incumbent providers can be onboarded, scoped, queried, suspended and exited without identity or ownership corruption;
4. Native ERP/WMS/Trade/TMS boundaries demonstrate no unauthorised financial/stock/carrier effects;
5. Receiving, QC, bin, pick, pack, dispatch, count and exception scenarios have durable independent readback;
6. Two unrelated 3PL customers/stock owners are isolated within a real shared-operator test and service billing is reconciled;
7. Full positive, negative, concurrency, replay, ambiguous outcome, operator revocation, provider outage and recovery scenarios pass;
8. Supported GS1/EPCIS/EDI partner profiles pass version-specific conformance tests and unsupported profiles are accurately labelled;
9. Security, privacy, residency, observability, accessible operations and tested recovery meet the approved environment-specific quality budgets;
10. Exact-head real-source evidence supports each mandatory capability; no material requirement is waived through an unrecorded architectural exception.

**Completion of this list does not itself activate staging or production.** Protected deployment, external provider authority and sector-specific legal/certification gates are separately controlled.

## 24. Governing statement

> **Baobab-wms SHALL be an internationally competitive, provider-neutral warehouse and 3PL execution capability housed within baobab-erp. It SHALL turn verified physical warehouse activity into traceable, legally scoped business evidence; it SHALL neither replace the financial truth of iDempiere nor the commercial truth of Trade, transport truth of TMS, or legal authority of CP and responsible parties. A customer's existing capable warehouse provider is an integration choice—not a defect to be designed away.**

Quality is demonstrated through complete execution, verified isolation, accounting integrity, interoperable identifiers, lawful custody, measurable performance and independently repeatable evidence.

## 25. Source and standards references

**Baobab architecture**

- ERP-014: Master-data and attribute authority; ERP-015: Warehouse/inventory/3PL architecture; ERP-008/022: Financial and posting authority; ERP-020: Conformance/evidence.
- TMS-0017: Cargo custody and warehouse handoff; TMS-0020/0021: Hybrid provider adoption and provider lifecycle.
- Shared contracts: inventory-ownership/v1, erp/v1 warehouse and inventory availability, CP context, canonical events, capability provider and cross-engine references. These are existing contracts, not automatically revised by this ADR.

**International references — verify applicable version and partner specification at implementation time**

- GS1 General Specifications 26.0.0 — https://ref.gs1.org/standards/genspecs/
- GS1 EPCIS 2.0.1 — https://ref.gs1.org/standards/epcis/2.0.1/
- GS1 CBV 2.0 — https://ref.gs1.org/standards/cbv/2.0.0/
- ASC X12 transaction catalogue — https://x12.org/products/transaction-sets
- ISO 9001:2026 — https://committee.iso.org/standard/9001
- ISO/IEC 27001:2022; ISO 28000:2022; ISO 22301:2019; ISO 45001:2018 — https://www.iso.org/management-system-standards-list.html
- OWASP API Security Top 10 — https://owasp.org/API-Security/

**Standards boundary:** Referencing a standard in this ADR does not reproduce its restricted normative text or claim independent conformity or certification; implementation MUST obtain and assess relevant official specifications and current partner implementation guides.

---

**Disposition:** Proposed for architecture owner acceptance. No native technology selected, no WMS provider certified, no Shared operation key activated, no protected release approved.
