"""The ERP order-consequence read model's interpretation rules (ADR-ERP-016).

ERP derives an order's consequence status from the facts it observed itself: each native process it executed
successfully. It never copies a native DocStatus, and never reads Trade's status. Pure and database-free, so the rules are
tested without Postgres; the Postgres store only persists what this decides.

Facts and what they establish:

* the order was created (and mapped)             -> status ``accepted``
* the sales order was completed                  -> status ``processing``
* the goods shipment was completed               -> inventory ``fulfilled``
* the customer invoice was posted                -> accounting ``posted``
* accounting ``posted`` and inventory ``fulfilled`` -> status ``posted``

Anything not established stays ``pending``. Allocation, backorder, review, rejection and compensation need an observed
outcome that nothing produces yet (the held ERP events); they are representable in the store but are never inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

STATUSES = ("accepted", "processing", "posted", "needs_review", "rejected", "compensated")
ACCOUNTING_STATUSES = ("not_applicable", "pending", "posted", "needs_review", "failed")
INVENTORY_STATUSES = ("not_applicable", "pending", "allocated", "backordered", "fulfilled", "needs_review", "failed")


class Fact(StrEnum):
    ORDER_COMPLETED = "order_completed"
    SHIPMENT_COMPLETED = "shipment_completed"
    INVOICE_POSTED = "invoice_posted"


@dataclass(frozen=True, slots=True)
class Facts:
    order_completed: bool = False
    shipment_completed: bool = False
    invoice_posted: bool = False


@dataclass(frozen=True, slots=True)
class Derived:
    status: str
    accounting_status: str
    inventory_status: str


def derive(facts: Facts) -> Derived:
    accounting = "posted" if facts.invoice_posted else "pending"
    inventory = "fulfilled" if facts.shipment_completed else "pending"
    if accounting == "posted" and inventory == "fulfilled":
        status = "posted"
    elif facts.order_completed or facts.shipment_completed or facts.invoice_posted:
        status = "processing"
    else:
        status = "accepted"
    return Derived(status, accounting, inventory)


@dataclass(frozen=True, slots=True)
class OrderConsequence:
    tenant_id: str
    commerce_order_id: str
    legal_entity_id: str
    order_version: int
    erp_order_id: str
    status: str
    accounting_status: str
    inventory_status: str
    revision: int
    updated_at: datetime
    invoice_id: str | None = None
    exception_code: str | None = None

    def to_contract(self) -> dict:
        body = {
            "legal_entity_id": self.legal_entity_id, "commerce_order_id": self.commerce_order_id,
            "order_version": self.order_version, "erp_order_id": self.erp_order_id, "status": self.status,
            "accounting_status": self.accounting_status, "inventory_status": self.inventory_status,
            "revision": self.revision,
            "updated_at": self.updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if self.invoice_id is not None:
            body["invoice_id"] = self.invoice_id
        if self.exception_code is not None:
            body["exception_code"] = self.exception_code
        return body
