"""LA-05D4 / PEO-02T: current CP documentary negative-scope veto for ERP.

A CP result saying blocked=False is NOT finance, legal or provider authority.
Each operation must separately pass LA-04 legal actor + native iDempiere readiness.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Protocol

from shared_contracts import ContractViolation, validate_contract
from shared_contracts.http import RejectRedirect as _RejectRedirect

from order_to_cash.legal_actor_gate import LegalActorNotAuthorised, LegalActorOperation

POLICY = "ADR-BCP-026/PEO-02T:negative-only"
_MAX_LEASE = timedelta(seconds=2)
_MAX_AGE = timedelta(seconds=3)


class DocumentaryRestrictionAssessor(Protocol):
    def assess(self, request: Mapping[str, str]) -> Mapping[str, object]: ...


def restriction_request(operation: LegalActorOperation) -> dict[str, str]:
    operation.validate()
    return {
        "context_id": operation.context_id,
        "capability": operation.capability,
        "market": operation.market,
        "operation_reference": operation.operation_reference,
    }


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise LegalActorNotAuthorised("documentary restriction has no valid decision time")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LegalActorNotAuthorised("invalid documentary restriction validity") from exc
    if dt.tzinfo is None:
        raise LegalActorNotAuthorised("unbounded documentary restriction decision time")
    return dt.astimezone(timezone.utc)


def assert_documentary_scope_unblocked(
    operation: LegalActorOperation,
    raw: object,
    *,
    now: datetime,
) -> None:
    """No native invoice mutation unless an exact, fresh CP veto is FALSE."""
    operation.validate()
    try:
        validate_contract("documentary_response", raw)
    except ContractViolation as exc:
        raise LegalActorNotAuthorised("invalid canonical documentary decision") from exc
    if not isinstance(raw, Mapping) or now.tzinfo is None:
        raise LegalActorNotAuthorised("current CP documentary restriction unavailable")
    required = {
        "context_id": operation.context_id,
        "organisation_id": operation.operating_organisation_id,
        "capability": operation.capability,
        "market": operation.market,
        "operation_reference": operation.operation_reference,
        "policy_reference": POLICY,
    }
    if (
        any(raw.get(key) != value for key, value in required.items())
        or raw.get("blocked") is not False
        or raw.get("authority_granted") is not False
    ):
        raise LegalActorNotAuthorised("CP documentary scope blocked or mismatched")
    evaluated, expires = _instant(raw.get("evaluated_at")), _instant(raw.get("expires_at"))
    utc_now = now.astimezone(timezone.utc)
    if (
        evaluated > utc_now + timedelta(seconds=1)
        or utc_now - evaluated > _MAX_AGE
        or expires <= utc_now
        or expires <= evaluated
        or expires - evaluated > _MAX_LEASE
    ):
        raise LegalActorNotAuthorised("documentary scope lease expired or overlong")


def require_documentary_scope_unblocked(
    operation: LegalActorOperation,
    assessor: DocumentaryRestrictionAssessor | None,
    *,
    now: datetime,
) -> None:
    if assessor is None:
        raise LegalActorNotAuthorised("documentary restriction assessor not configured")
    try:
        raw = assessor.assess(restriction_request(operation))
        assert_documentary_scope_unblocked(operation, raw, now=now)
    except LegalActorNotAuthorised:
        raise
    except Exception as exc:
        # No optimistic allow on network failure, JSON corruption, timeout,
        # or runtime errors from a purported authoritative service.
        raise LegalActorNotAuthorised("documentary restriction authority unavailable") from exc


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("duplicate CP decision field")
        result[k] = v
    return result


class HttpControlPlaneDocumentaryRestrictionAssessor:
    """Private workload-authenticated PEO-02T request; no applicant claims."""

    def __init__(
        self, base_url: str, token_provider: Callable[[], str],
        correlation_provider: Callable[[], str], *,
        timeout: float = 3.0, opener=None,
    ) -> None:
        parts = urllib.parse.urlsplit(base_url)
        if (
            (parts.scheme != "https" and not (
                parts.scheme == "http" and parts.hostname == "localhost"
            ))
            or parts.username or parts.password or parts.query or parts.fragment
            or not parts.netloc or parts.path not in ("", "/")
            or timeout <= 0 or timeout > 10
        ):
            raise ValueError("documentary restriction requires explicit HTTPS CP origin")
        self._base = base_url.rstrip("/")
        self._token = token_provider
        self._correlation = correlation_provider
        self._timeout = timeout
        self._open = (opener or urllib.request.build_opener(_RejectRedirect())).open

    def assess(self, request: Mapping[str, str]) -> Mapping[str, object]:
        try:
            validate_contract("documentary_request", request)
        except ContractViolation as exc:
            raise LegalActorNotAuthorised("invalid canonical documentary scope") from exc
        if (
            set(request) != {"context_id", "capability", "market", "operation_reference"}
            or any(not isinstance(v, str) or not v.strip() for v in request.values())
            or re.fullmatch(r"[A-Z]{2}", request["market"]) is None
            or re.fullmatch(r"[a-z][a-z0-9._-]{2,199}", request["capability"]) is None
        ):
            raise LegalActorNotAuthorised("invalid documentary scope request")
        try:
            token = self._token()
            correlation = self._correlation()
            if not isinstance(token, str) or not token.strip() or not correlation:
                raise ValueError("missing IAM-issued workload token")
            body = json.dumps(dict(request), separators=(",", ":"), sort_keys=True).encode()
            http = urllib.request.Request(
                self._base + "/internal/documentary/v1/restrictions/assess",
                data=body, method="POST",
                headers={
                    "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                    "Cache-Control": "no-store", "X-Correlation-ID": correlation,
                },
            )
            with self._open(http, timeout=self._timeout) as response:
                if getattr(response, "status", 200) != 200:
                    raise ValueError("non-200 restriction response")
                payload = response.read(16_385)
            if len(payload) > 16_384:
                raise ValueError("oversized CP decision")
            value = json.loads(payload, object_pairs_hook=_unique_json)
            validate_contract("documentary_response", value)
            if not isinstance(value, dict):
                raise ValueError("CP decision is not an object")
            return value
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                OSError, ValueError, TypeError) as exc:
            raise LegalActorNotAuthorised("current documentary scope unavailable") from exc
        except Exception as exc:
            raise LegalActorNotAuthorised("authenticated documentary scope unavailable") from exc
