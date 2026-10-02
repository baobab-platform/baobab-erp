"""RFC 9457 problem documents shaped by contracts/errors/v1/problem-details.schema.json."""

import re
import uuid

_TRACEPARENT = re.compile(r"^00-(?!0{32})([0-9a-f]{32})-(?!0{16})[0-9a-f]{16}-[0-9a-f]{2}$")
PROBLEM_BASE = "https://contracts.baobab-platform.com/problems/erp/"

# status, title, retryable, code
_KNOWN = {
    "invalid_request": (400, "Invalid request", False, "ERP_INVALID_REQUEST"),
    "unauthenticated": (401, "Authentication required", False, "ERP_AUTHENTICATION_REQUIRED"),
    "forbidden": (403, "Not authorised", False, "ERP_FORBIDDEN"),
    "tenant_context_required": (403, "Tenant context required", False, "ERP_TENANT_CONTEXT_REQUIRED"),
    "not_found": (404, "Resource not found", False, "ERP_RESOURCE_NOT_FOUND"),
    "not_implemented": (501, "Operation not implemented", False, "ERP_OPERATION_NOT_IMPLEMENTED"),
}


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
            instance: str | None = None, errors: list[dict] | None = None) -> tuple[int, dict]:
    status, title, retryable, code = _KNOWN[kind]
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
