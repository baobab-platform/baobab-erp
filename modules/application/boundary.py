"""ERP Boundary API (contracts/erp/v1/openapi.yaml), the read surface backed by real data.

Pure request -> (status, body) logic; server.py owns HTTP, authentication and the connection.
The resolved tenant claim is the only tenant authority: nothing in a request can widen it.

Implemented: GET /mappings/{mapping_id}, GET /mappings, POST /provisioning-operations and
GET /provisioning-operations/{operation_id} (application.provisioning_operations).
Declared but not implemented (answered 501 problem+json after authorisation, never fabricated):
GET /order-consequences/{commerce_order_id}, GET /inventory-availability.
See architecture/conformance.yaml (ADR-ERP-005) for what each is waiting on.
"""

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs

from application.problem import problem
from application.provisioning_operations import get_provisioning_operation, request_provisioning
from mapping import identifiers
from mapping.model import CANONICAL_OWNERS

_RESOURCE_TYPE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAPPING_PATH = re.compile(r"^/mappings/([^/]+)$")
_PROVISIONING_OPERATION = re.compile(r"^/provisioning-operations/([^/]+)$")
_NOT_IMPLEMENTED = (
    re.compile(r"^/order-consequences/[^/]+$"),
    re.compile(r"^/inventory-availability$"),
)
SCOPE_READ = "erp:read"


@dataclass(frozen=True, slots=True)
class BoundaryRoute:
    scope: str
    handler: Callable[..., tuple[int, dict]]
    argument: str | None = None


def match(method: str, path: str) -> BoundaryRoute | None:
    """The route for a boundary request, or None for a path that is not part of the contract.
    A trailing /v1 base path is stripped by the caller."""
    if method == "GET" and path == "/mappings":
        return BoundaryRoute(SCOPE_READ, find_mappings)
    if method == "GET":
        found = _MAPPING_PATH.fullmatch(path)
        if found:
            return BoundaryRoute(SCOPE_READ, get_mapping, found.group(1))
    if method == "POST" and path == "/provisioning-operations":
        return BoundaryRoute("erp:provision", request_provisioning)
    if method == "GET":
        operation = _PROVISIONING_OPERATION.fullmatch(path)
        if operation:
            return BoundaryRoute(SCOPE_READ, get_provisioning_operation, operation.group(1))
    if method in ("GET", "POST") and any(pattern.fullmatch(path) for pattern in _NOT_IMPLEMENTED):
        return BoundaryRoute(SCOPE_READ if method == "GET" else "erp:provision", not_implemented)
    return None


def not_implemented(*, correlation_id, trace_id, **_) -> tuple[int, dict]:
    return problem(
        "not_implemented", correlation_id=correlation_id, trace_id=trace_id,
        detail="This boundary operation is declared by the contract but its backing capability is not available yet.",
    )


def get_mapping(*, tenant_id, store, argument, correlation_id, trace_id, **_) -> tuple[int, dict]:
    try:
        identifiers.mapping_id(argument)
    except identifiers.IdentifierError:
        return problem("invalid_request", correlation_id=correlation_id, trace_id=trace_id,
                       detail="mapping_id is not a canonical mapping identifier",
                       errors=[{"code": "ERP_INVALID_IDENTIFIER", "message": "must match the canonical mapping identifier grammar",
                                "field": "mapping_id"}])
    mapping = store.get_mapping(tenant_id, argument)
    if mapping is None:
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id)
    try:
        return 200, mapping.to_contract()
    except ValueError:
        # An unreconciled mapping is not part of the public contract; to the caller it does not exist.
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id)


def find_mappings(*, tenant_id, store, query_string, correlation_id, trace_id, **_) -> tuple[int, dict]:
    query = parse_qs(query_string, keep_blank_values=True)
    owner, resource_type, resource_id = (_one(query, k) for k in ("owner", "resource_type", "resource_id"))
    problems = []
    if owner not in CANONICAL_OWNERS:
        problems.append(("owner", "must be a canonical owner"))
    if not (resource_type and len(resource_type) <= 63 and _RESOURCE_TYPE.fullmatch(resource_type)):
        problems.append(("resource_type", "must be a snake_case resource type"))
    if not (resource_id and 3 <= len(resource_id) <= 128 and _RESOURCE_ID.fullmatch(resource_id)):
        problems.append(("resource_id", "must be an opaque canonical resource id"))
    extra = sorted(set(query) - {"owner", "resource_type", "resource_id"})
    problems.extend((name, "unknown query parameter") for name in extra)
    if problems:
        return problem("invalid_request", correlation_id=correlation_id, trace_id=trace_id,
                       errors=[{"code": "ERP_INVALID_PARAMETER", "message": msg, "field": name} for name, msg in problems])
    items = []
    for mapping in store.find_mappings(tenant_id, owner, resource_type, resource_id):
        try:
            items.append(mapping.to_contract())
        except ValueError:
            continue
    return 200, {"items": items}


def _one(query: dict, name: str) -> str | None:
    values = query.get(name)
    return values[0] if values and len(values) == 1 else None
