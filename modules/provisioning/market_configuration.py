"""ERP-owned deployment configuration for provisioning: per-market currencies, localisation profile and warehouses
(ADR-ERP-009, ADR-ERP-015), the native placement of each legal entity (ADR-ERP-002 SS114, ADR-ERP-021) and the target
environment.

Control Plane does not store these, so ERP supplies them from deployment configuration, never from a request and never as
a default. A market whose entry still holds a ``REQUIRED_*`` placeholder is NOT configured: the loader leaves it out, so
provisioning that market fails closed until someone fills it in. Structural mistakes (wrong grammar, missing member, an
unknown member) raise rather than being skipped, because a typo must not look like "not configured yet".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from dataclasses import dataclass

from provisioning.cp_contract import ErpMarketConfiguration
from provisioning.warehouse import WarehousePolicyError, check_warehouse_timezones
from provisioning.legal_entity_policy import ConfiguredNativePlacementPolicy, NativePlacement

_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_LEGAL_ENTITY = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_PLACEHOLDER = "REQUIRED_"
_MEMBERS = frozenset({"currencies", "localisation_profile", "warehouse_codes", "warehouse_timezones"})


class MarketConfigurationError(ValueError):
    pass


def _placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith(_PLACEHOLDER)
    if isinstance(value, list):
        return any(_placeholder(item) for item in value)
    if isinstance(value, Mapping):
        return any(_placeholder(item) for item in value.values())
    return False


@dataclass(frozen=True, slots=True)
class DeploymentConfiguration:
    markets: dict[str, ErpMarketConfiguration]
    native_placement: ConfiguredNativePlacementPolicy
    target_environment: str


_TOP_LEVEL = frozenset({"schema_version", "status", "target_environment", "markets", "native_placements"})


def parse_deployment_configuration(document: Any) -> DeploymentConfiguration:
    if not isinstance(document, Mapping) or set(document) - _TOP_LEVEL:
        raise MarketConfigurationError(f"deployment configuration must be an object with only {sorted(_TOP_LEVEL)}")
    environment = document.get("target_environment")
    if not isinstance(environment, str) or not environment.strip() or environment.startswith(_PLACEHOLDER):
        raise MarketConfigurationError("target_environment must be set (no placeholder)")
    placements = document.get("native_placements", {})
    if not isinstance(placements, Mapping):
        raise MarketConfigurationError("native_placements must be an object keyed by canonical legal entity id")
    configured: dict[str, NativePlacement] = {}
    for legal_entity, entry in placements.items():
        if not _LEGAL_ENTITY.fullmatch(legal_entity):
            raise MarketConfigurationError(f"{legal_entity!r} is not a canonical legal entity id")
        if not isinstance(entry, Mapping) or set(entry) != {"native_client_key"}:
            raise MarketConfigurationError(f"{legal_entity}: needs exactly ['native_client_key']")
        key = entry["native_client_key"]
        if not isinstance(key, str) or not key.strip():
            raise MarketConfigurationError(f"{legal_entity}: native_client_key must be a non-blank string")
        if not key.startswith(_PLACEHOLDER):
            configured[legal_entity] = NativePlacement(key.strip())
    return DeploymentConfiguration(parse_market_configuration(document), ConfiguredNativePlacementPolicy(configured),
                                   environment.strip())


def parse_market_configuration(document: Any) -> dict[str, ErpMarketConfiguration]:
    if not isinstance(document, Mapping):
        raise MarketConfigurationError("market configuration must be an object")
    markets = document.get("markets")
    if not isinstance(markets, Mapping):
        raise MarketConfigurationError("markets must be an object keyed by ISO 3166-1 alpha-2 country")
    configured: dict[str, ErpMarketConfiguration] = {}
    for country, entry in markets.items():
        if not _COUNTRY.fullmatch(country):
            raise MarketConfigurationError(f"{country!r} is not an ISO 3166-1 alpha-2 country code")
        if not isinstance(entry, Mapping) or set(entry) != _MEMBERS:
            raise MarketConfigurationError(f"{country}: needs exactly {sorted(_MEMBERS)}")
        if any(_placeholder(entry[m]) for m in _MEMBERS):
            continue  # an explicit placeholder is "not configured yet"
        currencies, profile, warehouses = entry["currencies"], entry["localisation_profile"], entry["warehouse_codes"]
        if not isinstance(currencies, list) or not currencies or len(set(currencies)) != len(currencies) \
                or not all(isinstance(c, str) and _CURRENCY.fullmatch(c) for c in currencies):
            raise MarketConfigurationError(f"{country}: currencies must be a non-empty list of distinct ISO 4217 codes")
        if not isinstance(profile, str) or not profile.strip():
            raise MarketConfigurationError(f"{country}: localisation_profile must be a non-blank string")
        if not isinstance(warehouses, list) or not warehouses or len(set(warehouses)) != len(warehouses) \
                or not all(isinstance(w, str) and w.strip() for w in warehouses):
            raise MarketConfigurationError(f"{country}: warehouse_codes must be a non-empty list of distinct codes")
        try:
            zones = check_warehouse_timezones(warehouses, entry["warehouse_timezones"])
        except WarehousePolicyError as exc:
            raise MarketConfigurationError(f"{country}: {exc}") from None
        configured[country] = ErpMarketConfiguration(tuple(currencies), profile.strip(), tuple(warehouses), zones)
    return configured


def load_deployment_configuration(path: str | Path) -> DeploymentConfiguration:
    try:
        return parse_deployment_configuration(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as exc:
        if isinstance(exc, MarketConfigurationError):
            raise
        raise MarketConfigurationError(f"cannot read deployment configuration {path}: {exc}") from exc
