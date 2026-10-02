"""Identifier grammars from the Shared contracts (control-plane/v1 and erp/v1 domain schemas).

ERP persists and validates these; it never mints a tenant or legal-entity id (ADR-BCP-018).
Only mapping_id and erp_resource_id are minted here, by the ERP boundary.
"""

import re
import uuid

_TENANT_ID = re.compile(r"^tn_[a-z0-9]+$")
_LEGAL_ENTITY_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_MAPPING_ID = re.compile(r"^map_[a-z0-9]+$")
_ERP_RESOURCE_ID = re.compile(r"^erp_[a-z0-9]+$")


class IdentifierError(ValueError):
    pass


def _check(value: object, pattern: re.Pattern[str], name: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high or not pattern.fullmatch(value):
        raise IdentifierError(f"{name} does not match the canonical contract grammar: {value!r}")
    return value


def tenant_id(value: object) -> str:
    return _check(value, _TENANT_ID, "tenant_id", 6, 63)


def legal_entity_id(value: object) -> str:
    return _check(value, _LEGAL_ENTITY_ID, "legal_entity_id", 3, 63)


def mapping_id(value: object) -> str:
    return _check(value, _MAPPING_ID, "mapping_id", 8, 63)


def erp_resource_id(value: object) -> str:
    return _check(value, _ERP_RESOURCE_ID, "erp_resource_id", 8, 63)


def new_mapping_id() -> str:
    return "map_" + uuid.uuid4().hex


def new_erp_resource_id() -> str:
    return "erp_" + uuid.uuid4().hex
