"""RFC 9457 problem documents shaped by contracts/errors/v1/problem-details.schema.json."""

import re
import uuid

_TRACEPARENT = re.compile(
    r"^00-(?!00000000000000000000000000000000)([0-9a-f]{32})-(?!0000000000000000)[0-9a-f]{16}-[0-9a-f]{2}$"
)
PROBLEM_BASE = "https://contracts.baobab-platform.com/problems/erp/"

# status, title, retryable, code
_KNOWN = {
    "invalid_request": (400, "Invalid request", False, "ERP_INVALID_REQUEST"),
    "unauthenticated": (401, "Authentication required", False, "ERP_AUTHENTICATION_REQUIRED"),
    "forbidden": (403, "Not authorised", False, "ERP_FORBIDDEN"),
    "tenant_context_required": (403, "Tenant context required", False, "ERP_TENANT_CONTEXT_REQUIRED"),
    "not_found": (404, "Resource not found", False, "ERP_RESOURCE_NOT_FOUND"),
    "conflict": (409, "Conflict", False, "ERP_CONFLICT"),
    "not_implemented": (501, "Operation not implemented", False, "ERP_OPERATION_NOT_IMPLEMENTED"),
    "upstream_rejected": (502, "Upstream system rejected the request", False, "ERP_UPSTREAM_REJECTED"),
    "unavailable": (503, "Service unavailable", True, "ERP_SERVICE_UNAVAILABLE"),
    "internal": (500, "Internal error", True, "ERP_INTERNAL_ERROR"),
}
_BY_STATUS = {400: "invalid_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict",
              501: "not_implemented", 502: "upstream_rejected", 503: "unavailable", 500: "internal"}


def kind_for_status(status: int) -> str:
    return _BY_STATUS[status]


def correlation_id_from(header: str | None) -> str | None:
    """A caller-supplied X-Correlation-ID must be a UUID; absent means generate one. Returns
    None when the header is present but invalid."""
    if header is None:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(header))
    except ValueError:
        return None


def trace_id_from(traceparent: str | None) -> tuple[bool, str | None]:
    """(valid, trace_id). An absent header is valid with no trace id."""
    if traceparent is None:
        return True, None
    match = _TRACEPARENT.fullmatch(traceparent)
    return (True, match.group(1)) if match else (False, None)


def problem(kind: str, *, correlation_id: str, trace_id: str | None = None, detail: str | None = None,
            instance: str | None = None, errors: list[dict] | None = None, code: str | None = None) -> tuple[int, dict]:
    """``code`` names the specific condition (e.g. PLAN_AUTHORITY_MISMATCH) where the contract names one; otherwise the
    kind's generic code is used."""
    status, title, retryable, kind_code = _KNOWN[kind]
    code = code or kind_code
    body: dict = {
        "type": PROBLEM_BASE + kind.replace("_", "-"),
        "title": title,
        "status": status,
        "code": code,
        "correlation_id": correlation_id,
        "retryable": retryable,
    }
    if trace_id:
        body["trace_id"] = trace_id
    if detail:
        body["detail"] = detail[:2048]
    if instance:
        body["instance"] = instance[:512]
    if errors:
        body["errors"] = errors[:50]
    return status, body
