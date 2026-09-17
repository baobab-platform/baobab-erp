from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable


class WarehousePolicyError(ValueError): pass


@dataclass(frozen=True, slots=True)
class WarehouseDeclaration:
    code: str
    name: str
    legal_entity_id: str
    market_id: str
    country_code: str
    organisation_key: str
    active: bool = True


def validate_warehouses(
    declarations: Iterable[WarehouseDeclaration],
    *,
    legal_entity_id: str,
    market_id: str,
    country_code: str,
) -> tuple[WarehouseDeclaration, ...]:
    items=tuple(declarations)
    seen=set()
    for w in items:
        if w.code in seen: raise WarehousePolicyError(f"duplicate warehouse code {w.code}")
        seen.add(w.code)
        if w.legal_entity_id != legal_entity_id:
            raise WarehousePolicyError(f"{w.code}: cross-legal-entity warehouse")
        if w.market_id != market_id or w.country_code != country_code:
            raise WarehousePolicyError(f"{w.code}: warehouse market mismatch")
        if not w.organisation_key.strip():
            raise WarehousePolicyError(f"{w.code}: explicit ERP organisation mapping required")
    return items
