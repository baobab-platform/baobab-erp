# ADR-ERP-025 — Autonomous Enterprise Product Monorepo and Replaceable Engine Architecture

**Status:** **Accepted — authoritative ERP-local repository composition and product-family architecture, 12 November 2026.** Product implementation, Shared capability registrations, provider qualification, engine replacement, protected deployment and commercial activation remain independent gates.  
**Decision class:** ERP / product architecture / monorepo / domain boundaries / headless engine portability / provider neutrality / native accounting / release governance  
**Repository:** baobab-platform/baobab-erp  
**Decision owner:** Baobab Platform Owner and Enterprise Architecture  
**Implementation owner:** Baobab ERP engineering; product maintainers act under accepted Shared/CP/IAM authority  
**Governing baseline:** EA v2.3, EA-DEV, EA-XB v1.1; ADR-ERP-001–024; applicable accepted Shared, CP, IAM, Trade, TMS and Payments contracts  
**Primary precedents:** ADR-ERP-023 (People), ADR-ERP-024 (WMS), ADR-ERP-001/004 (headless ERP and extension boundaries), ADR-ERP-008/015/022 (accounting and inventory authority)  
**Related work:** ERP #116 (manufacturing), ERP #117 (CRM); neither issue by itself qualifies a runtime or grants a canonical capability

## 1. Decision

Baobab SHALL develop its ERP-adjacent enterprise product family in **one modular monorepo**, baobab-platform/baobab-erp, with independently governed product modules, explicitly replaceable headless execution providers and shared enterprise authority.

The initial identified product portfolio is:

1. **Baobab Finance** — financial management, accounting, consolidation and financial-control experience.
2. **Baobab People** — HRMS/HCM, workforce, attendance, talent, payroll and employee experience.
3. **Baobab WMS** — warehouse execution, fulfilment, physical custody and 3PL services.
4. **Baobab Manufacturing** — manufacturing operations, MRP/MES, production, quality and work-in-progress coordination.
5. **Baobab Supply Chain Management (SCM)** — sourcing, procurement, supplier collaboration and supply planning.
6. **Baobab CRM** — lead, account relationship, opportunity, sales pipeline and service interactions.
7. **Baobab Assets** — enterprise asset lifecycle, maintenance, reliability and asset operations.
8. **Baobab Projects** — portfolio/project delivery, resources, budgets, costs and project services.
9. **Baobab Quality** — cross-domain inspection, nonconformance, traceability and corrective/preventive action, subject to product-admission evidence.
10. **Baobab Service Management** — service/field-service operations, work dispatch and service obligations, subject to product-admission evidence.

Finance, People, WMS, Manufacturing, SCM and CRM are designated **first-wave product boundaries** for architecture/capability assessment; this is not a declaration that those runtimes are implemented, qualified or activated. Assets, Projects, Quality and Service Management are designated **candidate product boundaries** pending a documented admission decision. Further products MAY be added through the product-admission process in Section 13.

The repository SHALL retain the current ERP **engine boundary** and existing evidence. Product names and directory layout do not mint canonical Engine, Capability, CapabilityProvider, Tenant, LegalEntity, subscription or activation state.

**Governing principle: Independent products. Shared enterprise authority. Replaceable engines.**

## 2. Core architectural correction: iDempiere is a current provider, not a permanent product dependency

The accepted platform architecture deliberately separates headless engines from canonical business contracts so that engines can be replaced without rebuilding Baobab's tenant, identity, commerce, digital estate or product interfaces.

**iDempiere 13 is the currently selected native ERP implementation and authoritative writer for accounting and other explicitly bound ERP transactions. It is not a permanently mandated vendor or framework for every enterprise product.**

Accordingly:

- Shared SHALL own canonical capability semantics, contracts, versions and event envelopes; no product or iDempiere plugin may independently redefine them.
- CP SHALL own tenant, legal-entity, market, capability/provider/EngineInstance binding, qualification, effective scope and runtime selection; IAM SHALL independently attest identity and authority.
- The active, qualified finance/ERP provider SHALL own financial posting within the exact legal entity, ledger/book, period and operation scope of its binding. **When iDempiere is the active provider**, its native commit-time financial veto, document semantics, posting rules and audit trail are mandatory.
- Baobab product-domain APIs, workflows and user experiences SHALL depend on **business-defined ports and canonical contracts**, not directly on iDempiere AD_Client/AD_Org, C_BPartner, M_Product, Fact_Acct, 2Pack or OSGi types.
- Vendor-specific behavior SHALL be isolated in a replaceable anti-corruption adapter. Native extensions are allowed only where the selected provider requires them; they SHALL NOT become public platform semantics.
- A future provider (or tenant's incumbent system) MAY fulfil a product capability only after independent eligibility, fidelity, security, financial/legal equivalence where applicable, migration and replay qualification.
- Replacing an execution provider SHALL NOT imply that finance, physical custody, payroll, commerce reservation or manufacturing state automatically transfers to the new provider, or that unsupported operations become available.

**Replaceable does not mean interchangeable without migration or certification.** Existing legal records, opening balances, accounting history, native transaction identifiers, audit provenance, regulatory retention, financial reconciliation and reversal obligations must survive a controlled cutover.

ADR-ERP-001 remains the accepted iDempiere implementation profile until separately superseded or amended. This ADR makes its vendor-specific assumptions explicitly **provider-local** and does not silently weaken ADR-ERP-001/002/004/008/015/022.

## 3. Vocabulary: product, module, provider, engine and enterprise authority

| Concept | Meaning | Must not be confused with |
| --- | --- | --- |
| **Product** | Independently governed business offering with its own roadmap, experience, capabilities, entitlements, releases and support | Git repository, tenant, accounting ledger |
| **Module** | Cohesive source/package boundary within the ERP monorepo | Mandatory standalone runtime or Engine |
| **Execution provider** | Selected native, Baobab-managed or external system implementing a bounded business operation | Source of canonical identity or implied financial authority |
| **Engine / EngineInstance** | Shared/CP-registered platform execution and deployment topology | Product name or directory |
| **Canonical capability** | Shared-defined business operation and contract | Vendor method, iDempiere table, proposed spelling |
| **Enterprise authority** | Scope-limited system of record and permission to commit a specific consequential effect | Co-location in one repository/cluster |
| **ProductSubscription** | CP-governed commercial entitlement to product functionality | Unrestricted access to all shared ERP native services |

A product MAY have its own headless service or frontend, a native iDempiere OSGi extension, an external-provider adapter, or a combination. It remains a product boundary, not a new engine by implication.

## 4. Common foundation and dependency direction

The monorepo SHALL organise reusable, non-domain-specific ERP foundation capabilities separately from product business logic. Existing source paths SHALL move only through tested migration increments; the logical layout below is not evidence that directories already exist.

    baobab-erp/
      platform/                       # shared ERP-boundary infrastructure
        context/ identity/ mapping/ security/
        contracts/ events/ outbox/ inbox/
        provisioning/ reconciliation/ observability/
        provider-resolution/ adapter-spi/
      products/
        finance/
        people/
        wms/
        manufacturing/
        scm/
        crm/
        assets/
        projects/
        quality/
        service-management/
      idempiere/
        extensions/ vendor/ patches/  # selected provider implementation
      db/                             # governed native and Baobab migrations
      contracts/                      # ERP-owned profiles consuming Shared
      tests/                          # product, adapter, cross-product, negatives
      deploy/ docs/ architecture/

No placeholder application modules are required just to match this tree. Existing modules/, idempiere/extensions/, db/ and experimental People paths SHALL remain functional until migration is demonstrated.

Required dependency direction:

    Product experience / business workflows
                   |
                   v
          Product-owned ports
                   |
                   v
         Qualified adapter interface
                   |
         +---------+----------+
         |                    |
         v                    v
    iDempiere adapter     Other qualified provider
         |                    |
         +----------+---------+
                    |
          Governed evidence/events
                    |
        Shared / CP / IAM authority

The diagram does not imply bypassing the selected provider's actual transactional boundary. For native iDempiere execution, its supported process/OSGi/API and commit-time controls still apply.

**Architecture constraints:**

1. Platform foundation SHALL NOT depend on a product implementation.
2. Products SHALL NOT import another product's private persistence or internal business logic; approved shared domain contracts or explicitly versioned ports are required.
3. Products SHALL NOT directly read or mutate another engine's database.
4. Only selected native adapters SHALL import or expose provider-specific classes/types.
5. A product SHALL NOT introduce a shadow canonical tenant registry, role store, ledger, inventory valuation authority or payment rail.
6. Direct browser-to-privileged CP/IAM/ERP access SHALL NOT replace server-side delegated authorisation.
7. Contract tests and static dependency checks SHOULD enforce these rules in CI; exceptions require a reviewed and expiring architecture decision.

## 5. Product portfolio and authoritative scope

| Product boundary | Owns (subject to accepted contract) | Native/provider boundary and non-ownership |
| --- | --- | --- |
| **Finance** | Financial operations experience; financial planning, close, consolidation, AP/AR workflows and reconciliation | Active qualified ERP accounting provider owns ledger, posting, tax-book and financial document truth; not all ERP functionality is Finance |
| **People** | Employment, recruitment, leave, attendance, benefits, performance, learning, payroll orchestration, employee self-service | Qualified selected payroll provider owns exact result; finance provider owns optional journal; Payments/Treasury owns disbursement |
| **WMS** | Physical receiving/picking/packing, warehouse tasks, custodian observations, 3PL customer operations | Custody != ownership; finance/inventory provider owns accounting stock/valuation; Trade owns channel reservation; TMS owns transport |
| **Manufacturing** | BOM/routing intent, demand/capacity planning, production execution, shop-floor observations, quality and genealogy | Active ERP/manufacturing provider owns qualified native production/material and WIP/costing consequences; no invented Fact_Acct |
| **SCM** | Procurement orchestration, supplier qualification, sourcing/RFQ, replenishment, supply planning, supplier performance | ERP procurement provider owns native PO, goods receipt, AP; Trade owns commercial RFQ/commitments where applicable; WMS/TMS execute their own domains |
| **CRM** | Leads, engagement, opportunities, account relationship views, pipeline and service interactions | CP owns canonical Organisation/PlatformAccount; Trade owns checkout/buyer commitment; ERP owns invoice/order posting; Closed Won is not an order |
| **Assets** | Asset lifecycle, maintenance plans, asset performance, reliability and inspections | Qualified finance provider owns capitalisation, depreciation, disposal and asset ledger postings |
| **Projects** | Project/portfolio delivery, schedules, resources, timesheets, delivery evidence and governance | Qualified finance provider owns cost posting, commitments and project accounting; People owns employment |
| **Quality** | Cross-domain inspection/certification workflows, holds, CAPA, nonconformance and quality evidence | WMS/manufacturing own physical action; inventory release and accounting remain with applicable authorised provider |
| **Service Management** | Service cases, SLA execution, field dispatch, service workforce coordination and warranty operations | CRM owns relationship view, People owns workforce, Assets owns equipment, Finance owns financial results |

Each proposed product owner SHALL deliver a source-of-truth and CRUD/command authority matrix before implementing consequential mutations. Overlapping words such as supplier, account, inventory, order, work order, reservation, asset and payment SHALL NOT imply a single shared record.

### 5.1 Baobab Finance

Finance is the first-party financial product, **not a forced dependency on its commercial subscription for every ERP-adjacent product**. Internal posting integration may be available under explicitly granted ERP capabilities without exposing all Finance product screens/features.

The initial implementation uses iDempiere for native financial and ERP transactional authority under ADR-ERP-008/022. An alternative qualified ERP provider must demonstrate equivalent posting veto, double-entry balance, controlled correction/reversal, legal-entity isolation, accounting periods, immutable audit, idempotency and independently reconstructed ledger history before replacing that binding.

### 5.2 Baobab People — ADR-ERP-023 continues to govern

People retains permanent BYOP/hybrid/native provider choice for workforce, attendance, leave, payroll and statutory functions. CDSoftware is selectively reusable material, not a mandatory product substrate. Country/localisation qualification is separate (ZA first, UG next). Neither an employment relationship nor payroll approval authorises IAM access, GL posting or bank release. Rust is an eligible calculation implementation only after benchmark, functional, security and statutory proof.

### 5.3 Baobab WMS — ADR-ERP-024 continues to govern

WMS retains native-managed, external and hybrid provider options. Physical custody, customer/depositor, inventory owner, carrier, Commerce available-to-sell and native financial inventory remain separately attributable. No warehouse completion creates automatic accounting or title transfer. Warehouse execution technology remains a dedicated evidence-based decision.

### 5.4 Baobab Manufacturing

ERP issue #116 establishes an engineering investigation, not a certified manufacturing capability. Manufacturing SHALL evaluate actual pinned iDempiere 13 installed bundles, BOM/routing, MRP, work orders, WIP, material consumption, yield/scrap, quality, serial/lot traceability, native financial consequence and provider licensing before choosing adopt/adapt/replace.

An MES or Rust executor MAY be separately deployed within the repo. It may record attested operational observations, but production, stock and cost effects require the current qualified native/provider transaction, with CP legal-actor mandate and native commit veto where iDempiere is active.

### 5.5 Baobab Supply Chain Management

SCM SHALL provide supplier/procurement and replenishment orchestration, not duplicate Trade, TMS, WMS or ERP native transaction ownership. It must distinguish commercial RFQ/quotation, ERP purchase requisition/PO, physical receipts, supplier invoices and accounting effects; use canonical cross-engine references and governed provider handoffs.

### 5.6 Baobab CRM

ERP issue #117 is the research/qualification workstream. CRM SHALL be provider-neutral, able to use suitable native or existing CRM services where independently qualified. It SHALL NOT equate CRM Account with CP PlatformAccount or assume a buyer is a Baobab subscriber. A Closed Won stage may produce intent, but never self-authorise checkout, order, invoice or financial posting; Trade and ERP retain exact commit fences.

### 5.7 Baobab Assets and Projects

These product candidates SHALL first assess native iDempiere asset/project functions, lawful external providers, overlapping People/Finance/SCM domains and viable independent customer journeys. Native accounting consequences stay with the selected qualified finance provider. Project execution is not project ledger authority; equipment custody is not ownership.

### 5.8 Baobab Quality and Service Management

These are **candidate** cross-domain products, not automatic new engines or deployed service replicas. Quality SHALL distinguish advisory/inspection evidence from warehouse release, manufacturing disposition and native stock or financial change. Service Management SHALL preserve CRM relationship, People employee authority, Assets equipment and Finance posting boundaries. Their promotion requires a separate admission decision.

## 6. Provider neutrality and headless-engine replacement

Provider neutrality SHALL be an enforceable platform feature, not simply an exit strategy.

**6.1 Selection:** For each relevant capability, CP SHALL resolve the eligible provider/EngineInstance and required tenant, legal entity, market, jurisdiction, operation, environment, time window, isolation, residency and binding generation. IAM attests current identity; neither a UI field nor an environment variable grants authority. Unknown/unbound/unqualified means **deny**, not silent fallback to iDempiere or a first-party module.

**6.2 Provider ports:** Every consequential product operation SHALL specify business semantics, preconditions, postconditions, error/unknown states, immutable evidence, replay/idempotency, native reference mapping, data/export ownership and financial/legal side effects. Adapters SHALL isolate vendor and version-specific transport/schema details.

**6.3 Qualification:** A provider's success is counted only when its actual execution, bounded authority, independent readback, negative isolation tests, versioned contracts, replay/recovery and required financial/statutory/locality evidence are witnessed. A source-only mock is not a qualified runtime.

**6.4 Cutover:** A replacement requires an approved migration and rollback plan: inventory of in-flight commitments and documents; export of source and record provenance; mapping and data conversion; opening balances where accounting changes; lawful history retention; frozen/dual-read windows without dual authoritative writes; reconciliation; new CP binding generation; revocation of the old writer; and independent post-cutover evidence.

**6.5 In-flight operations:** The original bound provider remains accountable for a committed or unknown operation until resolved. Timeout is not evidence of failure. No replay through a second provider until the old outcome is independently established and policy permits it. Never silently transfer an outstanding payroll run, financial posting, manufacturing order or warehouse dispatch.

**6.6 Provider-independent consumers:** Digital estates and product interfaces SHALL not expose native iDempiere identifiers, direct database assumptions, or mandatory installation instructions as part of canonical business contracts. Provider migration may change internal adapters and storage but must preserve compatible public semantics or undergo a versioned contract transition.

**6.7 Reversibility limits:** Physical goods, bank money, legal records, tax returns, payments and historical ledgers are not simply rolled back by changing a binding. Product portability means controlled continuity and explicit compensating workflows, not deletion or binary database replacement.

## 7. Shared enterprise authority matrix

| Concern | Governing authority |
| --- | --- |
| Canonical vocabulary, API/events and contract versions | Shared |
| Tenant, Organisation, LegalEntity, ProductSubscription, Market, provider selection and capability bindings | CP |
| Human/workload identity, authentic issuer, scoped principal and step-up | IAM |
| Business-domain operational truth | Named, qualified selected product/provider under current binding |
| Accounting/financial posting, inventory valuation, ERP-native document status | Selected qualified ERP/finance provider; currently iDempiere under ADR-ERP-008/015/022 |
| Payroll calculation/return/payslip | Named, qualified People/payroll function provider, with independently qualified jurisdiction pack |
| Physical warehouse execution/custody | Selected qualified warehouse/WMS provider |
| Manufacturing execution | Selected qualified manufacturing provider; ERP material/financial consequences separately governed |
| Commercial checkout, buyer commitment and channel reservation | Trade under its accepted native controls |
| Transport planning and carrier execution | TMS and selected carrier under accepted TMS contracts |
| Bank-money movement and settlement | Authorised Payments/Treasury provider |
| Legal requirement source, evaluation and expert approval | Regulations and named human approver as applicable |
| Advisory intelligence and signals | Pulse, never an implicit operational approval |

**The source of truth is operation- and scope-specific.** It SHALL NOT be inferred from repository, corporate group, cloud account, database cluster, product name or technology.

## 8. Cross-product integration and data isolation

Internal package sharing is permitted only through documented, versioned interfaces and dependency direction. Cross-runtime effects SHALL use canonical API/event contracts, durable outbox/inbox or the selected engine's supported transactional APIs.

When operating inside the same qualified iDempiere transaction, supported native interfaces MAY coordinate native changes. Their transaction semantics SHALL NOT be simulated across different providers or databases.

Mandatory safeguards:

- independently verified tenant/legal-entity/context and current principal;
- original event/document ID, correlation and causal chain;
- immutable source-provider evidence and financial/legal scope;
- optimistic versions or equivalent fencing of stale mutations;
- idempotency and replay safety across outbox, broker and consumer;
- independently reconstructable failure and recovery evidence;
- purpose-based personal-data custody; employee/financial data not exposed to unrelated product readers;
- no cross-tenant access from common corporate affiliation or shared code;
- no direct cross-engine vendor table access or writes to native Fact_Acct/cost/stock internals.

Cross-product examples include People payroll-to-financial liabilities, WMS verified receipt-to-native inventory, Manufacturing material issue-to-WIP/costing, SCM purchase lifecycle-to-ERP AP, CRM opportunity-to-Trade *intent* (never buyer commitment), Assets maintenance-to-finance capitalisation, and Projects timesheet-to-project cost. Each requires its own bounded qualified provider and negative cases.

## 9. Product life cycle, packaging and commercial entitlement

Every admitted product SHALL have: stable product identity, accountable maintainer, scope/ownership matrix, capability inventory, canonical-contract version constraints, provider ports, dependency policy, security/PII classification, migration and export strategy, tests, and separately reviewable release notes.

- Product versioning MAY be independent. A People release need not advance WMS unless a shared foundational dependency genuinely changes.
- Independent packaging/deployment MAY be supported for an HTTP service, Rust worker, web experience or provider adapter, even while source is co-located. OSGi bundles sharing the same native JVM remain subject to its actual installation/compatibility constraints.
- Shared foundation or native integration changes SHALL run all affected product and cross-product CI, even if path-based optimisations normally skip unrelated tests.
- Product subscription is not a native ERP authorisation. A tenant can choose a standalone product or qualified subset without automatically receiving all Finance/People/WMS/etc. UI or mutation rights.
- CP SHALL derive provider/instance activation from accepted product/capability contracts and governance, not from a manifest's mere presence.
- No product SHALL require tenancy or subscription to all sibling products simply to use a certified external provider.
- No product SHALL forge a financial posting receipt by naming the Finance product; it must prove the actual bound finance provider performed the native consequence.

An ERP-managed product catalogue MAY offer multiple product subscriptions while the underlying ERP provider and deployment topology remain separate.

## 10. Polyglot implementation rules

Java/OSGi is the currently selected iDempiere native extension technology. Python services and Rust workers are permitted where evidence supports them, and TypeScript may power product user experiences. Technology selection SHALL consider native compatibility, performance, correctness, memory safety, staffing, recovery, supply chain, licence and provider portability.

Rust SHALL NOT become a reason to bypass iDempiere's current native financial controls. Conversely, a requirement to preserve iDempiere core SHALL NOT force standalone business calculation or execution code into the JVM where an independently governed component is demonstrably better.

JDK 21 remains the future target under ADR-ERP-023; the current deployable iDempiere 13 runtime remains Java 17 until exact-runtime qualification. PostgreSQL 17 is the established baseline, subject to safe migration and restore proof. No technology change is approved by this ADR alone.

## 11. Monorepo composition and repository boundaries

The source repository SHALL remain **baobab-platform/baobab-erp**. No physical split or rename is authorised by adoption of this ADR alone.

The future product organisation SHALL be incrementally aligned with platform/, products/, idempiere/, db/, contracts/, tests/, deploy/, docs/ and architecture/, without invalidating existing integrations, migration receipts, pinned dependencies or historical CI evidence.

- Core native iDempiere is externally maintained and SHALL NOT be long-lived forked (ADR-ERP-004).
- Product code SHALL avoid direct import of other products' private packages.
- Product contract types SHALL not expose vendor-specific data.
- Existing approved migration scripts SHALL be preserved; no source-only directory move may alter live data.
- Platform module code SHALL not import product implementations.
- The repo SHALL have a documented product-to-product and product-to-provider dependency graph.
- Separate Git repositories MAY be proposed in the future only after measured autonomy, ownership, release or regulatory needs justify the additional integration cost and a new approved architecture decision.

**Repo != product != runtime != engine != provider != tenant.**

## 12. Gate-based implementation programme

**ERP-MONO-00 — Baseline reconciliation.** Audit main/open PRs, Shared and CP pins, ERP #116/#117, accepted ADRs, current native accounting and DEV-07/09/11/12/14 implications. Publish source ownership, package dependency, event, database and CI inventories.

**ERP-MONO-01 — Portfolio census and admission.** Confirm all ten identified families, classify as approved/current/candidate, identify buyer personas and commercial jobs-to-be-done, overlap with existing engines, and exact system-of-record authority. No automatic new capability keys.

**ERP-MONO-02 — Product and foundation contracts.** Define business ports, native adapter seams, provider-selection semantics, error model, identity/mapping, data export, private/shared module boundaries and lifecycle manifests. Submit any new canonical keys/contracts to Shared.

**ERP-MONO-03 — Safe monorepo restructuring.** Move proven code incrementally under approved module boundaries without disabling existing tests or migrations. Establish import/dependency checks, CODEOWNERS where appropriate and package compatibility manifests. Product directories without live code are unnecessary.

**ERP-MONO-04 — Independent product CI/releases.** Product-local unit/contract/security tests and per-product versioning; shared change impact selection; native iDempiere/PG17 integration; independent release evidence; real Codespaces/devcontainer and private-package consumer qualification.

**ERP-MONO-05 — Replaceable-provider certification harness.** Prove current and replacement adapter contract parity, denial of unqualified providers, legal actor and binding-generation checks, exported historical data/mappings, replay/unknown resolution, revoked-old-provider refusal and roll-forward/compensation. Finance requires additional independently witnessed double-entry, balance, period, ledger-history and reversal checks.

**ERP-MONO-06 — Connected representative verticals.** At minimum: People payroll -> separately governed ERP liability -> Payments handoff; WMS custody -> ERP stock/valuation; Manufacturing BOM/consumption/WIP -> ERP financial trace; SCM supplier/PO/receipt/AP; CRM opportunity -> buyer-authorised Trade intent (not auto-commit); Assets/Projects/Quality/Service only when separately admitted. Include wrong employer/tenant, stale native binding, duplicate/out-of-order events, committed-result loss, and provider outage.

**ERP-MONO-07 — Product readiness and optional engine migration.** Sign independent production support, market/provider/localisation/legal requirements under ADR-ERP-020 and EA-09; demonstrate controlled migration only when a replacement actually exists. Do not equate CI green or an adapter mock with qualified engine substitutability.

Gate completion SHALL be evidenced with exact source SHA, provider/version/contract pins, live runtime receipts where required, independent verifier output, remediation/rollback and explicit unresolved blockers.

## 13. Product admission and portfolio governance

The first-wave product list authorises architectural ownership assessment, not universal implementation. A new product or promotion of a candidate SHALL require:

1. a defensible bounded domain and independent user/business outcome, not simply a renamed iDempiere menu;
2. evidence of existing native iDempiere features and other relevant open-source/third-party products;
3. an adopt/adapt/replace/independently-build decision with licence/SBOM review;
4. an explicit authority and overlapping-engine matrix;
5. a provider-neutrality and engine-replacement assessment;
6. product entitlement and independent support model;
7. data/retention/residency, security, legal and compliance requirements;
8. minimum product-local and cross-product CI/qualification plan;
9. responsible maintainer, runbooks, migration-out and sustainability cost;
10. reviewed Shared contract/CP registry changes for any new capability or provider.

**No proliferation rule:** A directory or iDempiere menu is not a business product. Cross-cutting Quality and Service Management may remain modules of Manufacturing/WMS/Assets/CRM until independent product value and authority are demonstrated.

## 14. Mandatory invariants

- **ERP-MONO-01:** One governed ERP monorepo, multiple autonomous enterprise products.
- **ERP-MONO-02:** Products, modules, engines, providers, runtime instances, tenants and subscriptions remain distinct.
- **ERP-MONO-03:** Canonical contracts and IAM/CP authority take precedence over vendor implementations.
- **ERP-MONO-04:** iDempiere is the currently selected native provider, not an immutable platform dependency.
- **ERP-MONO-05:** Native iDempiere posting/financial/inventory controls remain mandatory for any operation executed through it.
- **ERP-MONO-06:** An alternate provider is not active or authoritative without independent qualification and CP binding.
- **ERP-MONO-07:** No product owns a competing financial ledger, canonical identity, commerce buyer commitment or Payments authority by name.
- **ERP-MONO-08:** No implied access or source-of-truth sharing from repository, corporate affiliation or product subscription.
- **ERP-MONO-09:** Cross-product and cross-provider integrations are versioned, attributed, idempotent and independently reconcilable.
- **ERP-MONO-10:** No direct cross-engine table access or unauthorised native financial mutations.
- **ERP-MONO-11:** People and WMS permanent BYOP and hybrid choices remain binding under ADR-ERP-023/024.
- **ERP-MONO-12:** In-flight/unknown operations retain original provider custody until safely resolved; no silent fallback/double effect.
- **ERP-MONO-13:** Repo restructuring SHALL preserve migration history, source provenance, rollback and exact runtime evidence.
- **ERP-MONO-14:** Product version/deployment autonomy is qualified, not assumed from source-code modularity.
- **ERP-MONO-15:** Rust/Java/Python/TypeScript decisions SHALL not weaken enterprise authority or infer production readiness.
- **ERP-MONO-16:** Accepted architecture != implemented capability != qualified provider != protected activation.

## 15. Alternatives and consequences

**Keep one undifferentiated ERP application — rejected.** Business-domain ownership, provider portability and product releases would remain opaque.

**Split all products into repos immediately — deferred.** Premature duplication of native integration, CI, contract/release coordination and security models increases cost and error surface. A later extraction may be approved on evidence.

**Hardwire all products to iDempiere — rejected.** Violates Baobab's headless-engine replacement principle, impedes tenants retaining qualified incumbent systems and conflates product with provider.

**Rewrite all native ERP behavior in first-party services — rejected.** Duplicates accounting and inventory integrity and creates competing systems of record.

**Autonomous product monorepo with provider ports and current qualified native ERP — accepted.** Preserves shared governance and present financial integrity while creating verifiable replacement paths.

Costs include stricter interface/version discipline, cross-product CI, dual representations during bounded migration, provider certification and complex cutover evidence. These costs are accepted rather than disguised.

## 16. Relationship to existing decisions

ADR-ERP-023 and ADR-ERP-024 remain **Accepted and binding** for People and WMS specifics; their ERP-local monorepo direction is retained. This ADR adds an enterprise product-portfolio model and makes provider replacement explicit for all qualified product families.

ADR-ERP-001 remains the current iDempiere execution profile; ADR-ERP-004 continues to prohibit ungoverned core forks; ADR-ERP-008, ADR-ERP-015 and ADR-ERP-022 continue to govern current native accounting, procurement, inventory, costing and commit-time veto. Any actual replacement of iDempiere requires an explicit provider/engine migration decision, accepted Shared/CP changes and independent proof; it is not a shortcut around those ADRs.

ERP #116 Manufacturing and ERP #117 CRM remain engineering workstreams, not claims of activated capability or provider certification. SCM SHALL not duplicate the separate Trade, TMS or WMS authorities; no new canonical engine is created for any product by this document.

## 17. Definition of done and non-activation

**ADR acceptance is complete by approval of this decision. Implementation conformance is NOT complete until ERP-MONO-00–07 are independently evidenced.**

Acceptance of this document SHALL NOT:

- move source files, rewrite database migrations or create a separate Git repository;
- change a CP engine/binding or activate an unqualified provider;
- register new canonical capabilities or ProductSubscriptions by implication;
- certify manufacturing, CRM, payroll country packs, WMS execution or engine replacement;
- permit live accounting, payment, customs, employment or warehouse authority without their separate gates;
- override protected staging/production approvals.

Future implementation PRs SHALL update architecture/conformance.yaml truthfully, identifying evidence, missing gates and any accepted exception.

**Final decision: Independent products; shared enterprise authority; replaceable headless engines. Standardise contracts and evidence, not vendors.**
