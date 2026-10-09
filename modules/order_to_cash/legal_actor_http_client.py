"""LA-05D2: authenticated, no-cache CP legal actor client for ERP PEP.

The caller MUST be the ERP workload that owns the supplied CP-minted RUNTIME
PlatformContext. This adapter transports a fact; only legal_actor_gate and the
iDempiere finance/provider adapter can permit irreversible operations.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Mapping

from provisioning.control_plane_client import ControlPlaneUnavailable

_ALLOWED_FIELDS = frozenset({
    "context_id", "role", "activity", "market", "capability", "operation_reference",
})
_REQUIRED = frozenset({"context_id", "role", "activity", "market", "operation_reference"})


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON property")
        result[name] = value
    return result


class HttpControlPlaneLegalActorAssessor:
    def __init__(
        self, base_url: str, token_provider: Callable[[], str],
        correlation_provider: Callable[[], str], *,
        timeout: float = 3.0, opener=None,
    ) -> None:
        parts = urllib.parse.urlsplit(base_url)
        if (parts.scheme != "https" and not (
                parts.scheme == "http" and parts.hostname == "localhost"
            )) or parts.username or parts.password or parts.query or parts.fragment or (
                not parts.netloc or parts.path not in ("", "/")
            ):
            raise ValueError("Control Plane legal-actor endpoint requires an explicit HTTPS origin")
        if timeout <= 0 or timeout > 10:
            raise ValueError("bounded Control Plane timeout required")
        self._base = base_url.rstrip("/")
        self._get_token = token_provider
        self._correlation = correlation_provider
        self._timeout = timeout
        self._open = (opener or urllib.request.build_opener()).open

    def assess(self, request: Mapping[str, str]) -> Mapping[str, object]:
        if (not isinstance(request, Mapping) or set(request) - _ALLOWED_FIELDS or
                not _REQUIRED.issubset(request) or
                any(not isinstance(v, str) or not v.strip() for v in request.values())):
            raise ControlPlaneUnavailable("invalid legal-actor operation context")
        try:
            token = self._get_token()
            correlation_id = self._correlation()
            if not token or not token.strip() or not correlation_id or not correlation_id.strip():
                raise ValueError("missing authenticated issuer evidence")
            body = json.dumps(dict(request), separators=(",", ":"), sort_keys=True).encode()
            http = urllib.request.Request(
                self._base + "/internal/legal-actor/v1/assess",
                data=body, method="POST",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Correlation-ID": correlation_id,
                    "Cache-Control": "no-store",
                },
            )
            with self._open(http, timeout=self._timeout) as response:
                # Cap potentially malicious upstream payload before parsing.
                payload = response.read(16_385)
            if len(payload) > 16_384:
                raise ValueError("oversized Control Plane response")
            decoded = json.loads(payload, object_pairs_hook=_without_duplicates)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError,
                ValueError, TypeError) as exc:
            raise ControlPlaneUnavailable("legal actor assessment unavailable or invalid") from exc
        except Exception as exc:  # noqa: BLE001 - issuer/token provider failures must deny
            raise ControlPlaneUnavailable("authenticated legal actor assessment unavailable") from exc
        if (not isinstance(decoded, dict) or
                decoded.get("context_id") != request["context_id"] or
                decoded.get("operation_reference") != request["operation_reference"] or
                decoded.get("provider_permissions_granted") is not False or
                not isinstance(decoded.get("legal_actor_resolution"), dict)):
            raise ControlPlaneUnavailable("Control Plane returned an unbound legal actor decision")
        return decoded
