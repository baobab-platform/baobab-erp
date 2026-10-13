"""Exact Shared wire validation, independent of operational authorisation.

P0-04A / ADR-ERP-005, ADR-BCP-026/027: malformed facts never reach a
consequential operation. Registry resources are immutable packaged bytes;
no network retrieval, coercion, property removal or optimistic fallback.
"""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


class ContractViolation(ValueError):
    """Canonical wire shape denied; do not expose upstream data in errors."""


_DATA = files(__package__).joinpath('data')
PROVENANCE = json.loads(_DATA.joinpath('provenance.json').read_bytes())
_registry = Registry()
for _path, _digest in PROVENANCE['files'].items():
    _raw = _DATA.joinpath(_path).read_bytes()
    if hashlib.sha256(_raw).hexdigest() != _digest:
        raise RuntimeError('Packaged Shared contract integrity failed')
    _schema = json.loads(_raw)
    Draft202012Validator.check_schema(_schema)
    _registry = _registry.with_resource(_schema['$id'], Resource.from_contents(_schema))
_FORMATS = Draft202012Validator.FORMAT_CHECKER
# Missing optional format dependencies must fail startup, not silently accept
# invalid timestamps. These dependencies are now installed in the runtime.
for _format, _invalid in [('date-time', '2026-02-30T03:00:00Z'), ('uuid', '1-1-1-1-1')]:
    if _FORMATS.conforms(_invalid, _format):
        raise RuntimeError('Required Shared format assertion is unavailable')
_VALIDATORS = {
    name: Draft202012Validator({'$ref': uri}, registry=_registry, format_checker=_FORMATS)
    for name, uri in PROVENANCE['entries'].items()
}


def validate_contract(name: str, instance: object) -> None:
    """Validate shape only; caller MUST still bind scope, actor and freshness."""
    try:
        _VALIDATORS[name].validate(instance)
    except ValidationError as exc:
        # Only canonical top-level field names are diagnostic; no input values.
        path = next(iter(exc.absolute_path), 'shape')
        owned = _registry.resolver().lookup(PROVENANCE['entries'][name]).contents.get('properties', {})
        field = path if isinstance(path, str) and path in owned else 'shape'
        raise ContractViolation(f'Invalid Shared {name} wire contract ({field})') from None
