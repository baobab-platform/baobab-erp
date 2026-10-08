"""The Trade order an ``order.placed`` event asks ERP to carry (Shared erp/v1 commerce-order-consequence.schema.json).

Ingress verifies the signature, the registered type, producer and dataschema URI, and records the event. Whether the
*payload* satisfies the contract is checked again here, before anything touches the engine, because an executor must not
trust that a stored row was ever validated: a payload that does not parse is a permanent failure of that event, never
guessed at. Only what ERP needs to create the order is read; unknown members are ignored here (ingress owns the closed
schema), but a member that is present must be well formed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from mapping import identifiers

_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
MAX_LINES = 500


class PayloadError(ValueError):
    """The event data is not a valid commerce order; carries a short, fixed reason (no payload content)."""


@dataclass(frozen=True, slots=True)
class PlacedLine:
    line_id: str
    sku_id: str
    quantity: str
    unit: str
    unit_price: str


@dataclass(frozen=True, slots=True)
class PlacedOrder:
    legal_entity_id: str
    commerce_order_id: str
    order_version: int
    customer_id: str
    currency: str
    lines: tuple[PlacedLine, ...]


def _resource_id(data: dict, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not _RESOURCE_ID.fullmatch(value):
        raise PayloadError(f"{name} is missing or not a canonical resource id")
    return value


def _decimal(value: Any, what: str, *, positive: bool) -> str:
    if not isinstance(value, str):
        raise PayloadError(f"{what} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise PayloadError(f"{what} is not a decimal") from None
    if not parsed.is_finite() or (positive and parsed <= 0) or parsed < 0:
        raise PayloadError(f"{what} is out of range")
    return value


def parse_placed_order(data: Any) -> PlacedOrder:
    if not isinstance(data, dict):
        raise PayloadError("data is not an object")
    legal_entity = data.get("legal_entity_id")
    try:
        identifiers.legal_entity_id(legal_entity)
    except identifiers.IdentifierError:
        raise PayloadError("legal_entity_id is missing or malformed") from None
    version = data.get("order_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PayloadError("order_version must be a positive integer")
    currency = data.get("currency")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise PayloadError("currency must be an ISO 4217 code")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > MAX_LINES:
        raise PayloadError("lines must be a non-empty list")
    lines, seen = [], set()
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise PayloadError("a line is not an object")
        line_id = _resource_id(raw, "line_id")
        if line_id in seen:
            raise PayloadError("line_id repeats")
        seen.add(line_id)
        quantity, price = raw.get("quantity"), raw.get("unit_price")
        if not isinstance(quantity, dict) or not isinstance(price, dict):
            raise PayloadError("a line needs quantity and unit_price objects")
        unit = quantity.get("unit")
        if not isinstance(unit, str) or not unit:
            raise PayloadError("a line quantity needs a unit")
        if price.get("currency") != currency:
            raise PayloadError("a line price is not in the order currency")
        lines.append(PlacedLine(line_id=line_id, sku_id=_resource_id(raw, "sku_id"),
                                quantity=_decimal(quantity.get("value"), "quantity", positive=True), unit=unit,
                                unit_price=_decimal(price.get("amount"), "unit_price", positive=False)))
    return PlacedOrder(legal_entity_id=legal_entity, commerce_order_id=_resource_id(data, "commerce_order_id"),
                       order_version=version, customer_id=_resource_id(data, "customer_id"), currency=currency,
                       lines=tuple(lines))
