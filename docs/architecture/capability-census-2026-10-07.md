# ERP Capability Census — 2026-10-07

**Repository:** `baobab-platform/baobab-erp`  
**Baseline:** `854b1d315e188f6f39295df31618aab31655518e` (`main`, after context-authority and CXF security convergence)  
**Governing model:** ADR-SHARED-017 and Shared EA-02 capability catalogue/review

## Purpose

This census separates:

1. **canonical tenant/business capabilities** that another Baobab consumer can resolve and invoke;
2. **engine implementation/plumbing** that must not become a capability;
3. **candidate future capabilities** whose authority or granularity is not yet settled; and
4. **open-PR evidence** that must not be claimed as `main` implementation.

A capability declaration is implementation evidence only. It is not Control Plane activation,
a CapabilityBinding, certification, health, tenant entitlement, or production readiness.

## Current canonical capability conclusions

| Capability | Canonical in Shared | ERP main evidence | Census status |
|---|---:|---|---|
| `finance.order-consequence.process` | Yes | Real order-to-cash execution, ERP-owned consequence read model, canonical consequence event, canonical query endpoint | **PARTIAL provider support** (inbox execution landed in #67; lifecycle stages and live proof open) |
| `inventory.availability.query` | Canonical in Shared (catalogued at authority revision 40d1807) | Canonical GET boundary, mapping-driven SKU/warehouse resolution, iDempiere physical-stock read (written against the REST contract; not yet run live), exact contract tests | **IMPLEMENTED provider support** (implementation axis only; not run against a live iDempiere) |

### finance.order-consequence.process

The repository now implements materially more than the original 2026-09-30 EA-02B census:

- `modules/order_to_cash/service.py` executes the sell-side ERP consequence flow;
- `modules/order_to_cash/consequence.py` owns the vendor-neutral consequence projection;
- `modules/order_to_cash/consequence_events.py` emits
  `com.baobab-platform.erp.order.consequence-changed.v1`;
- `modules/application/boundary.py` serves the canonical
  `GET /order-consequences/{commerce_order_id}` query;
- contract and integration tests cover the projection and event shape.

Update 2026-10-08 (reconciled with main after #67 and #68): canonical
`com.baobab-platform.trade.order.placed.v1` is now executed. `baobab-inbox-worker` claims received
events under a lease, finds or adopts the engine order by `POReference` under a per-order lock, and in one
transaction records the consequence projection, the order link, the canonical outcome event and the inbox
outcome. Replay, a second worker, and a restart after an uncertain outcome do not create a second sales order
(`tests/integration/test_order_inbox_execution.py`). Provisioning now persists the EngineInstance with the tenant mapping (#68).

The capability is still **PARTIAL**, not `IMPLEMENTED`, for two reasons:

1. the order lifecycle after placement (shipment, invoice and accounting stages) is not driven from canonical events;
2. nothing has run against a live iDempiere (see `architecture/conformance.yaml`).

Promotion criterion:

```text
canonical trade.order.placed -> inbox -> idempotent execution -> consequence projection + outcome event   (done, #67)
later lifecycle stages driven from canonical events                                                        (open)
run against a live iDempiere                                                                                (open)
```

When the open items are proven, change provider support from `PARTIAL` to `IMPLEMENTED`.

### inventory.availability.query

The original EA-02B review accepted this capability conditionally on two things:

1. an explicit Shared request schema; and
2. a conforming ERP route.

Both now exist:

- Shared: `contracts/erp/v1/inventory-availability-query.schema.json`;
- ERP: `modules/application/inventory_availability.py`;
- engine read: `modules/inventory/availability.py`;
- explicit mapping authority: `modules/inventory/mappings.py`;
- boundary route: `GET /inventory-availability`;
- integration/conformance coverage:
  `tests/integration/test_inventory_availability_handler.py`,
  `tests/integration/test_boundary_api.py`,
  `tests/conformance/test_http_contract.py`.

The implementation reads the ERP engine's physical stock, does not reuse Trade
reservations, returns no fabricated/stale figure when the engine cannot be read, and
fails closed for unmapped SKU/warehouse identities.

The Shared catalogue entry has landed (40d1807), so this provider declares contract major 1 as
`IMPLEMENTED`. That declaration still does not make the provider ACTIVE or CERTIFIED.

## Explicit non-capabilities

The following are necessary ERP platform surfaces but are not tenant/business
capabilities under ADR-SHARED-017 / EA-02B:

| Surface | Why it is not a capability |
|---|---|
| Context resolve / reverse resolve | Tenant/legal-entity authority plumbing |
| Canonical mapping reads | Cross-engine identity plumbing |
| ERP provisioning operations | Control Plane-driven engine lifecycle/provisioning |
| Outbox/inbox delivery | Event transport reliability |
| Reconciliation internals | Operational assurance mechanism |
| iDempiere Client/Org placement | Provider implementation detail |
| Master-data projection/bootstrap | Projection/integration mechanism; authority and consumer contract remain unsettled |
| Warehouse native creation | Provider implementation of ERP master data, not a consumer capability by itself |

These must not be added to the capability catalogue merely because APIs or modules exist.

## Open-PR / concurrent-development census

The repository is under concurrent development. Capability claims in
`.baobab/capability-provider.yaml` are therefore based only on `main`, unless a PR is
explicitly identified below as future evidence.

### Context-authority convergence — #56 / #57 / #59 merged

The caller-bound Control Plane context programme is now on `main` (merged 2026-10-07).
Provisioning, order-consequence and inventory boundaries validate the caller/context
relationship before storage or protected reads, distinguish caller rejection from ERP
validator/configuration failure, and preserve fail-closed behavior.

This is now landed capability-hardening evidence for both canonical ERP capabilities; it
is no longer merely open-PR evidence.

### CXF security convergence — #60 / #61 merged

The inherited iDempiere 13 SOAP/CXF runtime that carried CRITICAL CVE-2026-49875 was
removed because Baobab ERP does not use the SOAP/ADInterface surface. The image build
fails if any remaining OSGi bundle depends on that feature. CI, Security, Foundation,
Trivy and SBOM gates passed after removal. The obsolete CXF scan waivers were then
deleted, so future reintroduction cannot be hidden by historical ignore policy.

### ERP PRs #32–#35 — ZuriBeans buyer/commercial stack

These stacked branches contain useful domain work:

- Business Partner projection;
- buyer projection event consumption;
- buyer commercial profile decision and event publication.

They are old stacked PRs and are not a safe basis for a current provider support claim.
They also mix **projection/integration mechanics** with a potentially real business
capability: the ERP-owned commercial/credit/payment-terms decision.

The census therefore records the following future review item rather than inventing a
canonical key now:

> **Candidate:** a provider-neutral customer/commercial-finance capability for ERP-owned
> credit/payment-terms decisioning, after the ZuriBeans stack is rebased/reconciled and
> Shared decides granularity and semantic ownership.

Business Partner projection itself remains integration plumbing and should not become a
capability merely because a route exists.

### ZuriBeans, Nabhold and Thamani repositories

At census time:

- ZuriBeans' open PR is dependency/tooling work, not ERP capability integration;
- Nabhold has no open PR;
- Thamani's open PR is Foundation-governance work.

No digital-estate PR is therefore modified by this census. Future digital-estate
integration should consume capabilities through Control Plane resolution/bindings rather
than hard-code `baobab-erp.idempiere`.

## Candidate future ERP capabilities

These are **not** added to the canonical catalogue or provider declaration in this
increment:

| Candidate area | Current verdict | Revisit condition |
|---|---|---|
| ERP-owned buyer credit/payment-terms decision | Defer for Shared semantic review | Reconcile PRs #32–#35 and define provider-neutral request/response authority |
| Procurement / procure-to-pay | Not implemented | Real consumer workflow and Shared contract exist |
| Standalone invoice posting | Not separate today | A consumer needs it independently of `finance.order-consequence.process` |
| Standalone payment accounting | Not separate today | A consumer needs it independently of the order consequence lifecycle |
| Warehouse projection | Not separate today | A consumer contract emerges beyond ERP provisioning/master-data projection |
| ERP reporting / analytical export | Planned ADR area only | Replaceable Shared request/response contract and implementation exist |

## Provider declaration target

The intended declaration after Shared catalogues inventory availability is:

```text
baobab-erp.idempiere
    |
    +-- finance.order-consequence.process   PARTIAL
    |
    +-- inventory.availability.query        IMPLEMENTED
```

The declaration deliberately does not express:

- certification;
- ACTIVE lifecycle;
- health;
- EngineInstance;
- bindings;
- grants;
- tenant entitlement;
- routing.

Those remain Control Plane / EA-09 authorities.

## Next capability increments

1. ~~Land the Shared catalogue completion for `inventory.availability.query`~~ (done, Shared 40d1807).
2. ~~Publish the evidence-backed ERP provider declaration~~ (this PR).
3. ~~Implement canonical `trade.order.placed` inbox-to-order-consequence execution~~ (done, #67). Promote
   `finance.order-consequence.process` only after the lifecycle stages and a live-iDempiere run are proven.
4. Re-audit/rebase the ZuriBeans #32–#35 stack and decide whether its commercial decision
   warrants a new Shared capability or belongs within an existing finance/customer
   composition.
5. Keep Nabhold, ZuriBeans and Thamani consumers provider-neutral: resolve capability,
   never vendor/provider identity.

## Related

`docs/architecture/capability-census-additional-areas-2026-10-08.md` extends this census with the additional business
areas, an event-by-event inventory and the four-axes model (implementation, live-provider conformance, certification,
activation).
