"""ADR-SHARED-045 People selection: independent CP authority is mandatory.

The only external selector is CP. Neither the browser, HRIS nor payroll
provider may choose its own legal employer or provider binding. This module
never finalises payroll, sends employee records, posts GL or releases payments.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import ssl
from typing import Callable, Protocol
from urllib.parse import urlparse
from urllib.request import (
    HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)


class ProviderSelectionDenied(ValueError):
    """Restricted denial, intentionally without PII or external details."""


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ProviderSelectionDenied("Invalid provider selection time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderSelectionDenied("Invalid provider selection time") from error
    if parsed.tzinfo is None:
        raise ProviderSelectionDenied("Unbounded provider selection time")
    return parsed.astimezone(timezone.utc)


def _unique_json(raw: bytes, *, maximum: int = 32768) -> dict:
    if not isinstance(raw, bytes) or len(raw) > maximum:
        raise ProviderSelectionDenied("Provider authority response unavailable")
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ProviderSelectionDenied("Duplicate provider authority field")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as error:
        raise ProviderSelectionDenied("Invalid provider authority response") from error
    if not isinstance(value, dict):
        raise ProviderSelectionDenied("Invalid provider authority response")
    return value


def _endpoint(base_url: str, suffix: str) -> str:
    parsed = urlparse(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.port == 0):
        raise ProviderSelectionDenied("A verified HTTPS endpoint is required")
    return base_url.rstrip("/") + suffix


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        raise ProviderSelectionDenied("Provider redirects are forbidden")


def verified_https_post(url: str, data: bytes, bearer: str) -> bytes:
    """Strict TLS, no proxy/redirect, caller-supplied short-lived token only."""
    if not isinstance(bearer, str) or not bearer or any(c.isspace() for c in bearer):
        raise ProviderSelectionDenied("Workload credential unavailable")
    if not url.startswith("https://") or len(data) > 8192:
        raise ProviderSelectionDenied("Provider transport denied")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
    req = Request(url, data=data, headers={
        "Authorization": "Bearer " + bearer,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="POST")
    try:
        with opener.open(req, timeout=7.0) as response:
            if response.status != 200 or response.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ProviderSelectionDenied("Provider response rejected")
            raw = response.read(32769)
    except ProviderSelectionDenied:
        raise
    except Exception as error:
        raise ProviderSelectionDenied("Provider transport unavailable") from error
    if len(raw) > 32768:
        raise ProviderSelectionDenied("Provider response too large")
    return raw


class TokenSource(Protocol):
    def access_token(self, audience: str, scopes: tuple[str, ...]) -> str: ...


Transport = Callable[[str, bytes, str], bytes]


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    tenant_id: str
    legal_employer_id: str
    jurisdiction: str
    capability_key: str
    binding_id: str
    provider_id: str
    binding_revision: int
    source_of_record: str
    qualification_receipt_ref: str
    verified_at: datetime
    expires_at: datetime


_CAPABILITIES = frozenset({
    "workforce.employment.read", "workforce.employment.manage",
    "payroll.run.read", "payroll.evidence.attest",
})
_PROVIDER = re.compile(r"^provider_[a-z0-9]+$")
_BINDING = re.compile(r"^bind_[a-z0-9]+$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$")
_TENANT = re.compile(r"^tn_[a-z0-9]+$")
_LEGAL = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_ISO = re.compile(r"^[A-Z]{2}$")


def _exact_fields(document: dict, required: set[str], optional: set[str]) -> None:
    if not required.issubset(document) or document.keys() - (required | optional):
        raise ProviderSelectionDenied("Unrecognised provider selection fields")


class CPProviderSelector:
    """Read current CP-issued provider selection for a caller-owned Context.

    The caller supplies the *expected* employer/jurisdiction from separate
    verified business authority. These values are not sent to CP as claims.
    """

    def __init__(self, base_url: str, workload_tokens: TokenSource,
                 transport: Transport = verified_https_post):
        self._url = _endpoint(base_url, "/internal/people/v1/provider-selection/resolve")
        self._tokens = workload_tokens
        self._transport = transport

    def resolve(self, *, context_id: str, correlation_id: str, capability_key: str,
                tenant_id: str, legal_employer_id: str, jurisdiction: str,
                now: datetime) -> ProviderSelection:
        if (not isinstance(now, datetime) or now.tzinfo is None
                or capability_key not in _CAPABILITIES or not _REF.fullmatch(context_id)
                or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", correlation_id)
                or not _TENANT.fullmatch(tenant_id) or not _LEGAL.fullmatch(legal_employer_id)
                or not _ISO.fullmatch(jurisdiction)):
            raise ProviderSelectionDenied("Invalid scoped provider request")
        request = json.dumps({
            "context_id": context_id, "correlation_id": correlation_id,
            "capability_key": capability_key, "required_contract_version": 1,
        }, separators=(",", ":")).encode()
        token = self._tokens.access_token("baobab-control-plane", (
            "context:resolve", "people:provider:read",
        ))
        result = _unique_json(self._transport(self._url, request, token))
        _exact_fields(result, {"selection", "decision_ref", "revision", "status", "portability_enabled"},
                      {"previous_binding_id", "cutover_evidence_ref"})
        fields = result["selection"]
        if not isinstance(fields, dict):
            raise ProviderSelectionDenied("CP selection missing")
        _exact_fields(fields, {
            "tenant_id", "legal_employer_id", "jurisdiction", "capability_key",
            "binding_id", "provider_id", "binding_revision", "source_of_record",
            "effective_from", "verified_at", "expires_at", "qualification_receipt_ref",
        }, {"effective_until"})
        now = now.astimezone(timezone.utc)
        start, observed, expiry = (
            _timestamp(fields["effective_from"]), _timestamp(fields["verified_at"]), _timestamp(fields["expires_at"]),
        )
        until = _timestamp(fields["effective_until"]) if "effective_until" in fields else None
        if (result["status"] != "ACTIVE" or result["portability_enabled"] is not True
                or not isinstance(result["revision"], int) or isinstance(result["revision"], bool)
                or result["revision"] < 1 or result["revision"] != fields["binding_revision"]
                or fields["tenant_id"] != tenant_id or fields["legal_employer_id"] != legal_employer_id
                or fields["jurisdiction"] != jurisdiction or fields["capability_key"] != capability_key
                or not isinstance(fields["binding_revision"], int)
                or isinstance(fields["binding_revision"], bool) or fields["binding_revision"] < 1
                or fields["source_of_record"] not in ("NATIVE", "EXTERNAL")
                or not _BINDING.fullmatch(fields["binding_id"])
                or not _PROVIDER.fullmatch(fields["provider_id"])
                or not _REF.fullmatch(fields["qualification_receipt_ref"])
                or not _REF.fullmatch(result["decision_ref"])
                or now < start or not observed <= now < expiry or now - observed > __import__("datetime").timedelta(seconds=30)
                or expiry - observed > __import__("datetime").timedelta(seconds=30)
                or until is not None and not now < until):
            raise ProviderSelectionDenied("Selected provider not currently authorised")
        return ProviderSelection(
            tenant_id, legal_employer_id, jurisdiction, capability_key,
            fields["binding_id"], fields["provider_id"], fields["binding_revision"],
            fields["source_of_record"], fields["qualification_receipt_ref"], observed, expiry,
        )
