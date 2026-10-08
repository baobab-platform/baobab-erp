from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from zoneinfo import available_timezones

_TIMEZONE_SHAPE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+.-]+)+$")  # the Shared warehouse-projection grammar


class WarehousePolicyError(ValueError): pass


@dataclass(frozen=True, slots=True)
class WarehouseDeclaration:
    code: str
    name: str
    legal_entity_id: str
    market_id: str
    country_code: str
    organisation_mapping_id: str
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
        if not w.organisation_mapping_id.strip():
            raise WarehousePolicyError(f"{w.code}: explicit ERP organisation mapping required")
    return items


def check_warehouse_timezones(codes: Iterable[str], zones: Any) -> tuple[tuple[str, str], ...]:
    """The timezones declared for a market's warehouses: exactly one per code, each a real IANA identifier (membership in the timezone
    database, not just its shape: ``Africa/Kampalaa`` has the right shape). Returns (code, zone) pairs sorted by code.

    The database must be present. An environment without one cannot verify anything, so it fails closed here rather than accepting
    every well-formed name."""
    codes = tuple(codes)
    if not isinstance(zones, Mapping) or set(zones) != set(codes):
        raise WarehousePolicyError("warehouse_timezones must name exactly the warehouse codes, one timezone each")
    known = available_timezones()
    if not known:
        raise WarehousePolicyError("no IANA timezone database is installed, so warehouse timezones cannot be verified")
    for code, zone in zones.items():
        if not (isinstance(zone, str) and len(zone) <= 64 and _TIMEZONE_SHAPE.fullmatch(zone) and zone in known):
            raise WarehousePolicyError(f"{code}: {zone!r} is not an IANA timezone identifier such as Africa/Kampala")
    return tuple(sorted(zones.items()))
