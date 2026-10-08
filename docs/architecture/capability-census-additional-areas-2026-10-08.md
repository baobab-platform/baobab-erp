# ERP capability census: additional business areas and the event inventory

Date: 2026-10-08. Audited at ERP `main` `8dc1b79`, Shared pin `9e6e407` (`contracts.lock.yaml`).

This extends, and does not replace, the canonical-capability census in PR #58
(`docs/architecture/capability-census-2026-10-07.md`, `.baobab/capability-provider.yaml`). It makes **no change to the
provider declaration**. #58's declaration validates unchanged against Shared `9e6e407` and Shared `70f92ee`
(`capability_catalogue.py validate-declaration`). This document creates no canonical key and claims no support: a key exists
only through an accepted Shared change to `contracts/capability/v1/catalogue.yaml` (ADR-SHARED-017 §12).

## 1. Four separate questions

A capability can be ahead on one axis and behind on another. This census keeps them apart.

| Axis | Question | Authority | Example (inventory availability) |
|---|---|---|---|
| Implementation | Does repository code serve the contract, with tests? | ERP (declaration `implementation_status`) | Yes: `modules/inventory/availability.py`, boundary route, tests |
| Live-provider conformance | Has it run against a real iDempiere? | ERP conformance ledger (`architecture/conformance.yaml`) | **Not proven.** The module docstring says it "has not run against a live instance" and that the AD column names are unconfirmed |
| Certification | Has an independent process accepted it? | EA-09 | Not started |
| Activation | Is it bound, entitled and routed for a tenant? | Control Plane | Not ERP's to state |

"Implemented" in #58 is the first axis only. It is not a statement about the other three.

## 2. Additional business areas

Classes: **Implemented**, **Partial**, **Proposed** (architecture or intent, no Baobab code), **Out of scope** (no current
subsidiary needs it, or another engine owns it). "Consumer" means a repository that calls the capability; a contract alone is
not a consumer. Searching `baobab-trade` for `inventory-availability` and `order-consequences` found only ADRs and
`docs/architecture/engine-boundaries.md`, no code, so no running consumer of either ERP read was found.

**None of the additional capability areas assessed is fully implemented.** Existing inventory reads and order-to-cash code
remain real implementation evidence; they are the two canonical capabilities covered by #58, not these areas.

| Area | Class | ERP evidence | Actual consumer | Boundary to preserve | Shared decision first |
|---|---|---|---|---|---|
| Procurement | Proposed | ADR-ERP-015 §25-48 (requisition, PO, receipt, matching). No procurement code | None found; ZuriBeans sourcing is Trade's | ERP owns the legal entity's commitments and receipts | PO command/event contract |
| Fixed assets | Proposed | None | None | Custody and history distinct from depreciation (ADR-ERP-008) | Meaning of custody versus accounting asset |
| Warehouse operations | Partial (provisioning and a physical-stock read only) | `modules/provisioning/warehouse*.py`; `modules/inventory/availability.py`. No receiving, put-away, picking, transfer, dispatch or count | None found | Trade owns fulfilment state; ERP or a WMS owns physical execution | Execution command set |
| Quality and traceability | Proposed | ADR-ERP-015 §20 (lot), §42 (inspection, hold) | None | Regulations decides; ERP records inspections and applies approved controls | Lot identity, quarantine, Regulations hand-off |
| Workforce administration / HR | Proposed | None | None | IAM authenticates, Control Plane grants authority; employment never implies access | Employment record ownership |
| Time and attendance | Proposed | None | None | Capture and approval separate from payroll | Approved-hours contract |
| Payroll | Out of scope until a staffing need | None | None | Needs employing entity, jurisdiction, pay cycle, accountable operator; Uganda and South Africa as distinct profiles behind one contract | Verified provider support |
| Expenses | Proposed | None | None | Payments owns execution; ERP records obligation and accounting | Obligation contract with Payments |
| Projects and job costing | Proposed | None | None | Corporate project management differs from operational job costing | Which of the two ERP owns |
| Manufacturing | Out of scope | None | No subsidiary manufactures | Reopen if one does | n/a |
| Maintenance | Out of scope | None | None | May later sit behind a dedicated provider | n/a |

HR and payroll are separate families so a subsidiary can use ERP for employment records and leave and an external payroll
provider. Priority for review: procurement, warehouse execution, quality/lot, fixed assets; then workforce administration,
expenses, time recording.

## 3. Event inventory (ERP `main`)

Shared's registry gives ERP eight types to produce and two to consume (`modules/events/registry.py`).
**Two of the eight are produced; six are not.** A type counts as produced only if a code path builds it and records it in the
outbox.

| # | Type | Direction | Produced or consumed in code | Evidence |
|---|---|---|---|---|
| 1 | `erp.order.consequence-changed.v1` | Produce | **Produced** | `modules/order_to_cash/consequence_events.py` (`new_event`), recorded in the outbox by `order_to_cash/service.py:121`; `tests/conformance/test_events.py` |
| 2 | `erp.provisioning.changed.v1` | Produce | **Produced** | `modules/provisioning/command_events.py`, `command_store.py`; delivered over signed delivery (#64) |
| 3 | `erp.business-partner.changed.v1` | Produce | Not produced | Registry entry only; no `new_event` or `CloudEvent(` call names it |
| 4 | `erp.inventory.availability-changed.v1` | Produce | Not produced | Registry entry only |
| 5 | `erp.warehouse.changed.v1` | Produce | Not produced | Registry entry only |
| 6 | `erp.invoice.changed.v1` | Produce | Not produced | Registry entry only; `docs/events.md`: payload needs invoice number, total and due date ERP does not yet hold |
| 7 | `erp.payment.accounting-changed.v1` | Produce | Not produced | Registry entry only; payload needs amount and capture id |
| 8 | `customer.buyer-commercial-profile.changed.v1` | Produce | Not produced | Registry entry only (ERP owns authoritative credit; the older #32-#35 stack is unreconciled) |
| 9 | `trade.order.placed.v1` | Consume | **Received, not executed** | `POST /events/inbound` -> `inbox.receive` records it (`server.py:535`, `inbox/service.py`); nothing reads inbox rows or calls order-to-cash. `test_http_server.py::test_inbound_event_end_to_end` proves receipt only |
| 10 | `trade.customer.projected.v1` | Consume | **Received, not executed** | Same path; `integration/trade_projection*.py` is not called from the inbox |

Legacy-shaped order-to-cash step events (`erp.sales-order.accepted.v1` and similar) are recorded as `held` and never
delivered (`docs/events.md`). They are not canonical events.

The consume side is the larger gap, and it is what stops `finance.order-consequence.process` being `IMPLEMENTED`: a signed
`order.placed` is accepted with HTTP 200 and nothing then happens. That is the next increment (inbox execution). The six
missing producers are deliberately out of that increment.

## 4. Reconciliation with #58 and main

- #58 touches `.baobab/capability-provider.yaml`, `.github/workflows/foundation.yml` and its own census file. This change
  touches none of them, so the two cannot conflict. Merge order does not matter.
- Main has advanced past #58's base (`854b1d3`) by #62-#65; none of those touch #58's files.
- Disagreement to note: #58's census says Trade order-event execution is a gap but records no event inventory. Section 3 is
  that inventory.
- Stale ledger, not changed here: `architecture/conformance.yaml` (~line 195-201) still lists `GET /order-consequences`
  ("no consequence read model") and `GET /inventory-availability` ("no iDempiere stock query") as unavailable, which #52
  and #53 made false. It also records no live-iDempiere status for either route. Correcting it belongs with the change that
  can state live status truthfully; #58's `IMPLEMENTED` for inventory is the implementation axis only (section 1).
