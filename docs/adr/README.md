# Architecture Decision Records

## Superseded (Frappe/ERPNext era)

ADR-0001 through ADR-0005 described the original Frappe/ERPNext foundation. They are
superseded by ADR-ERP-001, which replaces ERPNext/Frappe with iDempiere as the Baobab ERP
engine. Kept for history; do not follow them for new work.

- [ADR-0001: Extend, do not fork, Frappe and ERPNext](ADR-0001-upstream-extension-model.md) — superseded by ADR-ERP-004
- [ADR-0002: Frappe site as ERP tenant isolation unit](ADR-0002-site-tenancy.md) — superseded by ADR-ERP-002/003
- [ADR-0003: Explicit canonical entity mappings to ERPNext](ADR-0003-canonical-mappings.md) — superseded by ADR-ERP-007
- [ADR-0004: REST and signed events before a broker](ADR-0004-integration-transport.md) — superseded by ADR-ERP-005/006
- [ADR-0005: MariaDB for ERPNext compatibility](ADR-0005-database.md) — superseded by ADR-ERP-008 (PostgreSQL)

## Accepted (iDempiere era)

- [ADR-ERP-001: Implement iDempiere as an isolated, headless, multi-tenant Baobab ERP engine](ADR-ERP-001%20—%20Implement%20iDempiere%20as%20an%20Isolated%2C%20Headless%2C%20Multi-Tenant%20Baobab%20ERP%20Engine.md)
- [ADR-ERP-002: ERP tenant, client and organization mapping](ADR-ERP-002%20—%20ERP%20Tenant%2C%20Client%20and%20Organization%20Mapping.md)
- [ADR-ERP-003: ERP EngineInstance isolation, regional deployment and data residency](ADR-ERP-003%20—%20ERP%20EngineInstance%20Isolation%2C%20Regional%20Deployment%20and%20Data%20Residency.md)
- [ADR-ERP-004: Baobab iDempiere extension architecture](ADR-ERP-004%20—%20Baobab%20iDempiere%20Extension%20Architecture.md)
- [ADR-ERP-005: Baobab ERP integration API architecture](ADR-ERP-005%20—%20Baobab%20ERP%20Integration%20API%20Architecture.md)
- [ADR-ERP-006: ERP canonical event architecture](ADR-ERP-006%20—%20ERP%20Canonical%20Event%20Architecture.md)
- [ADR-ERP-007: ERP canonical entity and external reference mapping architecture](ADR-ERP-007%20—%20ERP%20Canonical%20Entity%20and%20External%20Reference%20Mapping%20Architecture.md)
- [ADR-ERP-008: ERP financial, accounting and multi-currency architecture](ADR-ERP-008%20—%20ERP%20Financial%2C%20Accounting%20and%20Multi-Currency%20Architecture.md)
- [ADR-ERP-009: ERP market localisation, jurisdiction and regulatory architecture](ADR-ERP-009%20—%20ERP%20Market%20Localisation%2C%20Jurisdiction%20and%20Regulatory%20Architecture.md)
- [ADR-ERP-010: ERP security, identity, authorization and tenant-isolation architecture](ADR-ERP-010%20—%20ERP%20Security%2C%20Identity%2C%20Authorization%20and%20Tenant-Isolation%20Architecture.md)
- [ADR-ERP-011: ERP observability, audit, reconciliation and operational control architecture](ADR-ERP-011%20—%20ERP%20Observability%2C%20Audit%2C%20Reconciliation%20and%20Operational%20Control%20Architecture.md)
- [ADR-ERP-012: ERP high availability, backup, disaster recovery and business continuity architecture](ADR-ERP-012%20—%20ERP%20High%20Availability%2C%20Backup%2C%20Disaster%20Recovery%20and%20Business%20Continuity%20Architecture.md)
- [ADR-ERP-013: ERP deployment, release, upgrade and configuration management architecture](ADR-ERP-013%20—%20ERP%20Deployment%2C%20Release%2C%20Upgrade%20and%20Configuration%20Management%20Architecture.md)
- [ADR-ERP-014: ERP master data ownership, synchronisation and reference data architecture](ADR-ERP-014%20—%20ERP%20Master%20Data%20Ownership%2C%20Synchronisation%20and%20Reference%20Data%20Architecture.md)
- [ADR-ERP-015: ERP inventory, warehouse, procurement and supply-chain architecture](ADR-ERP-015%20—%20ERP%20Inventory%2C%20Warehouse%2C%20Procurement%20and%20Supply-Chain%20Architecture.md)
- [ADR-ERP-016: Commerce–ERP integration and order-to-cash architecture](ADR-ERP-016%20—%20Commerce–ERP%20Integration%20and%20Order-to-Cash%20Architecture.md)
- [ADR-ERP-017: ERP document, attachment, records retention and evidence architecture](ADR-ERP-017%20—%20ERP%20Document%2C%20Attachment%2C%20Records%20Retention%20and%20Evidence%20Architecture.md)
- [ADR-ERP-018: ERP reporting, analytics, data export and intelligence integration architecture](ADR-ERP-018%20—%20ERP%20Reporting%2C%20Analytics%2C%20Data%20Export%20and%20Intelligence%20Integration%20Architecture.md)
- [ADR-ERP-019: ERP provisioning, tenant and legal-entity onboarding, migration and decommissioning architecture](ADR-ERP-019%20—%20ERP%20Provisioning%2C%20Tenant%20and%20Legal-Entity%20Onboarding%2C%20Migration%20and%20Decommissioning%20Architecture.md)
- [ADR-ERP-020: ERP production readiness, governance and architecture conformance](ADR-ERP-020%20—%20ERP%20Production%20Readiness%2C%20Governance%20and%20Architecture%20Conformance.md)
- [ADR-ERP-022: native placement, document provenance and posting-authority enforcement](ADR-ERP-022%20—%20Native%20Placement%2C%20Document%20Provenance%20and%20Posting-Authority%20Enforcement.md)

- [ADR-ERP-023: Baobab People — African workforce, payroll, CDSoftware re-engineering and PostgreSQL 17](ADR-ERP-023%20%E2%80%94%20Baobab%20People%20African%20Workforce%2C%20Payroll%2C%20CDSoftware%20Re-engineering%20and%20PostgreSQL%2017.md)

See `architecture/conformance.yaml` for how far each of these is actually implemented.
