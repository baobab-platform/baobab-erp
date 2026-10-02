"""HTTP client for Control Plane's ERP assignment read (Shared control-plane/v1 ``getTenantProvisioningErpAssignment``).

``GET {base}/v1/tenants/{tenant}/provisioning/{provisioning}/erp-assignments/{legal_entity}`` under the
``erp-assignment:read`` workload scope. What each answer means to ERP:

* 200                     the assignment (parsed strictly by assignment_from_payload);
* 404 / 409               Control Plane did not establish authority (no such provisioning or legal entity, or its sources
                          disagree / the plan is not approved and executable): ``AssignmentNotEstablished``, a 409 to ERP's
                          caller, never retried and never repaired;
* 401 / 403 / 5xx / timeout / malformed body
                          Control Plane could not be used right now (including ERP's own credentials being refused):
                          ``ControlPlaneUnavailable``, a 503 to ERP's caller, safe to retry with the same Idempotency-Key.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from provisioning.cp_contract import AssignmentError, CpErpAssignment, assignment_from_payload


class ControlPlaneUnavailable(Exception):
    pass


class AssignmentNotEstablished(AssignmentError):
    """Control Plane answered that it has no executable, approved assignment for this legal entity."""

    def __init__(self, status: int, code: str | None, detail: str | None):
        super().__init__(f"Control Plane answered {status} {code or ''}: {detail or 'no assignment'}".strip())
        self.status, self.code, self.detail = status, code, detail


def _problem(error: urllib.error.HTTPError) -> tuple[str | None, str | None]:
    try:
        body = json.loads(error.read() or b"{}")
        return body.get("code"), body.get("detail")
    except (ValueError, AttributeError):
        return None, None


class HttpControlPlaneAssignmentSource:
    def __init__(self, base_url: str, token_provider: Callable[[], str], *, timeout: float = 5.0, opener=None) -> None:
        self._base = base_url.rstrip("/")
        self._token = token_provider
        self._timeout = timeout
        self._open = (opener or urllib.request.build_opener()).open

    def resolve_erp_assignment(self, *, tenant_id: str, tenant_provisioning_id: str, legal_entity_id: str,
                               correlation_id: str | None = None) -> CpErpAssignment:
        quoted = [urllib.parse.quote(part, safe="") for part in (tenant_id, tenant_provisioning_id, legal_entity_id)]
        url = f"{self._base}/v1/tenants/{quoted[0]}/provisioning/{quoted[1]}/erp-assignments/{quoted[2]}"
        try:
            token = self._token()
        except ControlPlaneUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - a token failure is "cannot use Control Plane now", never a 500
            raise ControlPlaneUnavailable("could not obtain a Control Plane access token") from exc
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        try:
            with self._open(urllib.request.Request(url, headers=headers, method="GET"), timeout=self._timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in (404, 409):
                code, detail = _problem(error)
                raise AssignmentNotEstablished(error.code, code, detail) from None
            raise ControlPlaneUnavailable(f"Control Plane answered {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ControlPlaneUnavailable("Control Plane could not be reached or answered unreadably") from exc
        try:
            return assignment_from_payload(payload)
        except (AssignmentError, KeyError, TypeError) as exc:
            # A 200 that is not a valid ErpAssignment is a Control Plane fault, not authority.
            raise ControlPlaneUnavailable(f"Control Plane returned an invalid assignment: {exc}") from exc


class ClientCredentialsTokenProvider:
    """OAuth2 client-credentials token for ERP's workload client, cached until shortly before it expires."""

    def __init__(self, token_url: str, client_id: str, client_secret: str, scope: str, *, timeout: float = 5.0,
                 clock: Callable[[], float] = time.monotonic, opener=None, leeway: float = 30.0) -> None:
        self._url, self._id, self._secret, self._scope = token_url, client_id, client_secret, scope
        self._timeout, self._clock, self._leeway = timeout, clock, leeway
        self._open = (opener or urllib.request.build_opener()).open
        self._lock = threading.Lock()
        self._cached: tuple[str, float] | None = None

    def __call__(self) -> str:
        with self._lock:
            now = self._clock()
            if self._cached and now < self._cached[1]:
                return self._cached[0]
            data = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self._id,
                                           "client_secret": self._secret, "scope": self._scope}).encode()
            request = urllib.request.Request(self._url, data=data, method="POST",
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with self._open(request, timeout=self._timeout) as response:
                    body = json.loads(response.read())
                token, lifetime = body["access_token"], float(body.get("expires_in", 0))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
                raise ControlPlaneUnavailable("the IAM token endpoint refused or did not answer") from exc
            self._cached = (token, now + max(0.0, lifetime - self._leeway))
            return token
