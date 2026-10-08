"""Caller-bound CP authority for ERP boundary operations (Shared ERP API 1.1).

The subject token is the actual authenticated incoming bearer, never a locally
asserted principal. CP authenticates a separate registered ERP validator and
checks ownership, audience, lifecycle and expiry. No local authority fallback.
"""
from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TENANT = re.compile(r"^tn_[a-z0-9]{3,60}$")


RUNTIME = "RUNTIME"
TENANT_PROVISIONING = "TENANT_PROVISIONING"
_PURPOSES = frozenset({RUNTIME, TENANT_PROVISIONING})
_AUTHORITY_MEMBERS = frozenset({"tenant_provisioning_id", "plan_id", "plan_version", "plan_digest"})
_PROVISIONING_ID = re.compile(r"^tp_[a-z0-9]+$")
_PLAN_ID = re.compile(r"^plan_[a-z0-9]+$")
_PLAN_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProvisioningAuthority:
    """The approved plan a TENANT_PROVISIONING context is bound to (control-plane/v1 ProvisioningContextAuthority)."""
    tenant_provisioning_id: str
    plan_id: str
    plan_version: int
    plan_digest: str


@dataclass(frozen=True, slots=True)
class ValidatedContext:
    """What the Control Plane vouched for: the tenant, and what the context is authority FOR.

    authority_purpose is always stated by the Control Plane (control-plane/v1 1.34.0) and never inferred here. A RUNTIME
    context acts for an ACTIVE tenant; a TENANT_PROVISIONING context acts, before activation, only for the operations
    its approved plan authorises, and carries that plan.
    """
    tenant_id: str
    purpose: str
    provisioning_authority: ProvisioningAuthority | None = None


class InvalidContext(ValueError):
    pass


class ContextRejected(Exception):
    """All CP authority refusals are indistinguishable to ERP's caller."""


class ContextUnavailable(Exception):
    pass


def request_context_id(method: str, body: bytes, query: str) -> str:
    try:
        if method == "POST":
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise InvalidContext("duplicate JSON member")
                    result[key] = value
                return result
            document = json.loads(body, object_pairs_hook=unique)
            value = document.get("context_id") if isinstance(document, dict) else None
        else:
            values = parse_qs(query, keep_blank_values=True).get("context_id", [])
            value = values[0] if len(values) == 1 else None
    except (ValueError, UnicodeError) as exc:
        raise InvalidContext("invalid context request") from exc
    if not isinstance(value, str) or not UUID.fullmatch(value):
        raise InvalidContext("context_id must be a UUID")
    return value


def validated_context(payload, context_id: str, *, now: datetime | None = None) -> ValidatedContext:
    """A successful CP answer must still be structurally valid, bounded, and state its purpose."""
    required = {"context_id", "tenant_id", "resolved_at", "expires_at", "authority_purpose"}
    allowed = required | {"market_id", "organisation_id", "provisioning_authority"}
    if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys() - allowed:
        raise ContextUnavailable("invalid CP validation response")
    tenant = payload["tenant_id"]
    if payload["context_id"] != context_id or not isinstance(tenant, str) or not TENANT.fullmatch(tenant):
        raise ContextUnavailable("invalid CP validation response")
    purpose = payload["authority_purpose"]
    if not isinstance(purpose, str) or purpose not in _PURPOSES:
        raise ContextUnavailable("invalid CP validation response")
    authority = _provisioning_authority(payload.get("provisioning_authority"), purpose, payload)
    try:
        times = []
        for field in ("resolved_at", "expires_at"):
            raw = payload[field]
            if not isinstance(raw, str) or not re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})", raw):
                raise ValueError("not a date-time")
            parsed = datetime.fromisoformat(raw.upper().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("unbounded timezone")
            times.append(parsed)
        resolved, expires = times
        current = now or datetime.now(timezone.utc)
        if not resolved <= current < expires:
            raise ContextRejected()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ContextUnavailable("invalid CP validation response") from exc
    for field in ("market_id", "organisation_id"):
        if field in payload and (not isinstance(payload[field], str) or not payload[field].strip()):
            raise ContextUnavailable("invalid CP validation response")
    if "market_id" in payload and not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", payload["market_id"]):
        raise ContextUnavailable("invalid CP validation response")
    if "organisation_id" in payload and not (3 <= len(payload["organisation_id"]) <= 128 and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", payload["organisation_id"])):
        raise ContextUnavailable("invalid CP validation response")
    return ValidatedContext(tenant, purpose, authority)


def _provisioning_authority(raw, purpose: str, payload: dict) -> ProvisioningAuthority | None:
    """The plan tuple exactly when the purpose is TENANT_PROVISIONING, and never otherwise. A provisioning context carries
    no business dimension (market, organisation): one that does is not what the contract describes."""
    if purpose == RUNTIME:
        if raw is not None or "provisioning_authority" in payload:
            raise ContextUnavailable("invalid CP validation response")
        return None
    if "market_id" in payload or "organisation_id" in payload:
        raise ContextUnavailable("invalid CP validation response")
    if not isinstance(raw, dict) or raw.keys() != _AUTHORITY_MEMBERS:
        raise ContextUnavailable("invalid CP validation response")
    version = raw["plan_version"]
    if not (isinstance(raw["tenant_provisioning_id"], str) and 6 <= len(raw["tenant_provisioning_id"]) <= 63
            and _PROVISIONING_ID.fullmatch(raw["tenant_provisioning_id"])
            and isinstance(raw["plan_id"], str) and 8 <= len(raw["plan_id"]) <= 63 and _PLAN_ID.fullmatch(raw["plan_id"])
            and isinstance(version, int) and not isinstance(version, bool) and version >= 1
            and isinstance(raw["plan_digest"], str) and _PLAN_DIGEST.fullmatch(raw["plan_digest"])):
        raise ContextUnavailable("invalid CP validation response")
    return ProvisioningAuthority(raw["tenant_provisioning_id"], raw["plan_id"], version, raw["plan_digest"])


# What the Control Plane says about the CALLER, by problem code and the status it comes with (control-plane/v1
# POST /platform-context/validate). Anything else, including a 401 for ERP's own validator token or a 403 for a
# validator that is not registered, is ERP's configuration or an outage, never the caller's fault: it must not be
# reported to every caller as a rejected context, so it stays unavailable (503) and retryable.
_CALLER_REJECTIONS = {
    ("SUBJECT_TOKEN_INVALID", 401), ("CONTEXT_NOT_FOUND", 404), ("TENANT_CONTEXT_MISMATCH", 403),
    ("TENANT_NOT_ACTIVE", 403), ("VALIDATION_FAILED", 400),
    # A provisioning context whose approved plan is stale, withdrawn or superseded, or whose provisioning is not in a
    # state that executes (control-plane/v1 1.34.0): the caller's context, so one more indistinguishable rejection.
    ("PROVISIONING_AUTHORITY_NOT_CURRENT", 403),
}


def _is_caller_rejection(exc: urllib.error.HTTPError) -> bool:
    try:
        raw = exc.read(65537)
        if len(raw) > 65536:
            return False
        code = json.loads(raw).get("code")
    except (OSError, ValueError, AttributeError, TypeError, http.client.HTTPException):
        # http.client.HTTPException covers IncompleteRead: a Control Plane that cuts the body short says nothing about the caller.
        return False
    return isinstance(code, str) and (code, exc.code) in _CALLER_REJECTIONS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpContextValidator:
    def __init__(self, base_url: str, token_provider: Callable[[], str], *, timeout: float = 5.0, opener=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password \
                or parsed.query or parsed.fragment:
            raise ValueError("invalid configured CP URL")
        self._url = base_url.rstrip("/") + "/v1/platform-context/validate"
        self._token = token_provider
        self._timeout = timeout
        self._open = (opener or urllib.request.build_opener(_NoRedirect())).open

    def validate(self, *, context_id: str, subject_token: str, correlation_id: str) -> ValidatedContext:
        try:
            validator_token = self._token()
            if not isinstance(validator_token, str) or not validator_token or any(c.isspace() for c in validator_token):
                raise ContextUnavailable("validator token unavailable")
            request = urllib.request.Request(
                self._url, method="POST",
                data=json.dumps({"context_id": context_id, "subject_token": subject_token}).encode(),
                headers={"Authorization": f"Bearer {validator_token}", "Content-Type": "application/json",
                         "Accept": "application/json", "X-Correlation-ID": correlation_id})
            with self._open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise ContextUnavailable("CP validation unavailable")
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ContextUnavailable("CP validation response too large")
                payload = json.loads(raw)
        except urllib.error.HTTPError as exc:
            if _is_caller_rejection(exc):
                raise ContextRejected() from None
            raise ContextUnavailable("CP validation unavailable") from None
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
            raise ContextUnavailable("CP validation unavailable") from exc
        return validated_context(payload, context_id)


def configured_validator(base_url: str | None, token_file: str | None):
    """An externally supplied CP-audience ERP access token, not an assertion or static secret.

    No grants are created here. Unregistered validators fail closed in CP.
    Read each time so deployment-managed short-lived token rotation is visible.
    """
    if not base_url and not token_file:
        return None
    if not base_url or not token_file:
        raise ValueError("ERP_CONTEXT_VALIDATION_URL and ERP_CONTEXT_VALIDATION_TOKEN_FILE must both be set")
    return HttpContextValidator(base_url, lambda: Path(token_file).read_text().strip())
