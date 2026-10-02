"""GET /inventory-availability (contracts/erp/v1/openapi.yaml): the engine's physical stock for one SKU and warehouse.

The token's tenant is the only tenant authority. The warehouse and SKU resolve through explicit mappings; stock is read live
from iDempiere (ADR-ERP-015), so an engine that cannot be reached answers 503 with no figure, never a stale or estimated one.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import parse_qs

from application.problem import problem
from integration.idempiere_client import IdempiereClient, IdempiereClientError
from inventory.availability import IdempiereStockReader, StockReadError, decimal_string
from inventory.mappings import PostgresInventoryMappings

_SKU_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_WAREHOUSE_ID = re.compile(r"^erp_[a-z0-9]+$")
RETRY_AFTER_SECONDS = "30"


def get_inventory_availability(*, tenant_id, query_string: str, connection, correlation_id: str, trace_id: str | None,
                               idempiere_for: Callable[[int], IdempiereClient] | None = None,
                               now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                               **_) -> tuple[int, dict, dict]:
    def fail(kind: str, detail: str | None = None, *, errors=None, headers=None):
        status, document = problem(kind, correlation_id=correlation_id, trace_id=trace_id, detail=detail, errors=errors)
        return status, document, headers or {}

    parameters = parse_qs(query_string, keep_blank_values=True)
    errors = []
    for name in sorted(set(parameters) - {"sku_id", "warehouse_id"}):
        errors.append({"code": "ERP_INVALID_PARAMETER", "message": "unknown parameter", "field": name})
    for name, grammar, grammar_name in (("sku_id", _SKU_ID, "canonical resource identifier"),
                                        ("warehouse_id", _WAREHOUSE_ID, "ERP resource identifier")):
        values = parameters.get(name, [])
        if len(values) != 1:
            errors.append({"code": "ERP_INVALID_PARAMETER", "message": "exactly one value is required", "field": name})
        elif not (3 <= len(values[0]) <= 128 if name == "sku_id" else 8 <= len(values[0]) <= 63) \
                or not grammar.fullmatch(values[0]):
            errors.append({"code": "ERP_INVALID_IDENTIFIER", "message": f"must be a {grammar_name}", "field": name})
    if errors:
        return fail("invalid_request", "the inventory query is invalid", errors=errors)
    sku_id, warehouse_id = parameters["sku_id"][0], parameters["warehouse_id"][0]

    mappings = PostgresInventoryMappings(connection)
    warehouse = mappings.warehouse(tenant_id, warehouse_id)
    if warehouse is None:
        return fail("not_found")
    product = mappings.product(tenant_id, warehouse.legal_entity_id, sku_id)
    if product is None:
        return fail("not_found")

    unavailable = lambda: fail("unavailable", "the engine's inventory could not be read; no figure is returned",  # noqa: E731
                               headers={"Retry-After": RETRY_AFTER_SECONDS})
    if idempiere_for is None:
        return unavailable()
    try:
        facts = IdempiereStockReader(idempiere_for(product.ad_client_id)).read(
            product_native_id=product.native_id, warehouse_native_id=warehouse.native_id)
    except (IdempiereClientError, StockReadError, OSError, TimeoutError):
        return unavailable()

    as_of = now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    quantity = lambda value: {"value": decimal_string(value), "unit": facts.unit}  # noqa: E731
    return 200, {"legal_entity_id": warehouse.legal_entity_id, "sku_id": sku_id, "warehouse_id": warehouse_id,
                 "on_hand": quantity(facts.on_hand), "erp_allocated": quantity(facts.allocated),
                 "erp_available": quantity(facts.available), "as_of": as_of, "revision": facts.revision}, {}
