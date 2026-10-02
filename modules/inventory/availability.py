"""Physical inventory availability, read live from the engine (ADR-ERP-015; contracts/erp/v1/inventory-availability.schema.json).

iDempiere is the authority for physical stock, so nothing is stored or cached on the Baobab side and nothing comes from
Trade. For one mapped product and warehouse this reads:

* on hand: ``M_StorageOnHand.QtyOnHand`` summed over the locators of the warehouse (``M_Locator.M_Warehouse_ID``);
* allocated: ``M_StorageReservation.Qty`` for sales reservations (``IsSOTrx``) of the product in the warehouse. This is
  engine-committed quantity; it is not a Trade or Medusa reservation;
* available: on hand less allocated, never below zero (an over-allocation stays visible as allocated > on hand);
* unit: the product's ``C_UOM.X12DE355`` code;
* revision: the latest ``Updated`` instant (epoch seconds) over the stock rows read, so it changes exactly when the engine's
  stock facts change, and 1 when the engine holds no row. It is a change marker, not a counter ERP maintains.

Any response that does not have the expected shape is a StockReadError (the caller answers 503), never a guess.
Code-complete against the REST plugin's documented list/get shape; like the rest of integration/idempiere_client it has not run
against a live instance, so the AD column names above are the first thing to confirm there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from integration.idempiere_client import Eq, IdempiereClient

_UOM_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]*$")


class StockReadError(Exception):
    """The engine answered, but not with stock facts ERP can trust."""


@dataclass(frozen=True, slots=True)
class StockFacts:
    on_hand: Decimal
    allocated: Decimal
    unit: str
    revision: int

    @property
    def available(self) -> Decimal:
        return max(self.on_hand - self.allocated, Decimal(0))


def _reference(value: Any, what: str) -> int:
    """A REST reference column is either the bare id or an object carrying it."""
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise StockReadError(f"{what} is not a record reference")
    return int(value)


def _quantity(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise StockReadError(f"{what} is not a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise StockReadError(f"{what} is not a number") from exc
    if not number.is_finite():
        raise StockReadError(f"{what} is not finite")
    return number


def _updated(value: Any) -> int:
    if not isinstance(value, str):
        raise StockReadError("a stock row has no Updated instant")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StockReadError("a stock row has an unreadable Updated instant") from exc
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return int(instant.timestamp())


def decimal_string(value: Decimal) -> str:
    """The contract's base-10 decimal string: no exponent, no float."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


@dataclass(slots=True)
class IdempiereStockReader:
    client: IdempiereClient

    def read(self, *, product_native_id: int, warehouse_native_id: int) -> StockFacts:
        unit = self._unit(product_native_id)
        locators = {
            _reference(row.get("M_Locator_ID", row.get("id")), "M_Locator_ID")
            for row in self.client.query("M_Locator", [Eq("M_Warehouse_ID", warehouse_native_id)], ["M_Locator_ID"])
        }
        on_hand, revision = Decimal(0), 0
        for row in self.client.query("M_StorageOnHand", [Eq("M_Product_ID", product_native_id)],
                                     ["M_Locator_ID", "QtyOnHand", "Updated"]):
            if _reference(row.get("M_Locator_ID"), "M_Locator_ID") in locators:
                on_hand += _quantity(row.get("QtyOnHand"), "QtyOnHand")
                revision = max(revision, _updated(row.get("Updated")))
        allocated = Decimal(0)
        for row in self.client.query("M_StorageReservation",
                                     [Eq("M_Product_ID", product_native_id), Eq("M_Warehouse_ID", warehouse_native_id),
                                      Eq("IsSOTrx", True)], ["Qty", "Updated"]):
            allocated += _quantity(row.get("Qty"), "Qty")
            revision = max(revision, _updated(row.get("Updated")))
        return StockFacts(on_hand=on_hand, allocated=allocated, unit=unit, revision=revision or 1)

    def _unit(self, product_native_id: int) -> str:
        product = self.client.get_record("M_Product", product_native_id)
        uom = self.client.get_record("C_UOM", _reference(product.get("C_UOM_ID"), "C_UOM_ID"))
        code = uom.get("X12DE355")
        if not isinstance(code, str) or not _UOM_CODE.fullmatch(code) or len(code) > 24:
            raise StockReadError("the product's unit of measure has no usable X12 code")
        return code
