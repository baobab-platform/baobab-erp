"""REST client for iDempiere's own REST API.

The application layer (`modules/application`) speaks canonical contracts; this module
is the only place that knows iDempiere's actual API shape, per ADR-ERP-005. No other
module should import this one directly for business logic -- go through
`modules/application` so the canonical/native boundary stays in one place.

Verified against the com.trekglobal.idempiere.rest.api / bxservice/idempiere-rest
OpenAPI spec (https://github.com/bxservice/idempiere-rest, fetched 2026-09-06) rather
than assumed: login shape, token header, list/get/create/update paths and response
envelopes below are all taken directly from that spec.

Deployment note: this plugin is NOT part of the pinned idempiereofficial/idempiere
image -- it is a separate OSGi bundle installed into a running instance through
iDempiere's p2 provisioning mechanism. idempiere/Dockerfile now does that installation
for real (a verified update-prd.sh invocation), gated on a pre-built p2 repository
being present at idempiere/vendor/rest-api-p2/ (empty by default -- producing that
repository needs network access this environment doesn't have); see
idempiere/rest-api/README.md and architecture/conformance.yaml against ADR-ERP-005
and ADR-ERP-013.

Field-name note: the spec's own examples are inconsistent about casing for simple
scalar columns (`name` in some POST/PUT bodies, `Name` in every $filter/$select
example). Prefer real AD_Column names (PascalCase, e.g. `Name`, `IsActive`,
`C_BPartner_ID`) when building `fields` dicts -- that form is confirmed by multiple
independent examples in the spec. Verify empirically against a real instance before
relying on the lowerCamelCase form.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class IdempiereClientError(Exception):
    pass


class IdempiereAuthenticationError(IdempiereClientError):
    """Login, or an authenticated call whose token was rejected, failed."""


class IdempiereApiError(IdempiereClientError):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(f"{status} {title}: {detail}".strip())
        self.status = status
        self.title = title
        self.detail = detail


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_PAGE_SIZE = 100
_MAX_RECORDS = 5000


@dataclass(frozen=True, slots=True)
class Eq:
    """One ``column eq value`` condition. Conditions are typed and built here, never accepted as filter text, so a caller
    can neither widen a query nor inject into it: the column must be a plain AD column name and the value a number, a
    boolean or a string, which is quoted and escaped."""

    column: str
    value: int | bool | str


def build_filter(conditions: Sequence[Eq]) -> str:
    parts = []
    for condition in conditions:
        if not _IDENTIFIER.fullmatch(condition.column):
            raise ValueError(f"not a column name: {condition.column!r}")
        value = condition.value
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        elif isinstance(value, str):
            if any(ord(ch) < 32 for ch in value):
                raise ValueError("control characters are not allowed in a filter value")
            rendered = "'" + value.replace("'", "''") + "'"
        else:
            raise TypeError(f"unsupported filter value type: {type(value).__name__}")
        parts.append(f"{condition.column} eq {rendered}")
    return " and ".join(parts)


class IdempiereClient(Protocol):
    def get_record(self, table: str, record_id: int) -> dict[str, Any]: ...

    def query(self, table: str, conditions: Sequence[Eq], select: Sequence[str]) -> list[dict[str, Any]]: ...

    def create_record(self, table: str, fields: dict[str, Any]) -> int: ...

    def update_record(self, table: str, record_id: int, fields: dict[str, Any]) -> None: ...

    def execute_process(self, process_id: int, parameters: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class IdempiereEndpoint:
    base_url: str
    ad_client_id: int
    ad_org_id: int


class UnconfiguredIdempiereClient:
    """Raised-on-use placeholder until real credentials are supplied."""

    def __init__(self, endpoint: IdempiereEndpoint) -> None:
        self._endpoint = endpoint

    def get_record(self, table: str, record_id: int) -> dict[str, Any]:
        raise IdempiereClientError(f"No iDempiere client wired for {self._endpoint.base_url}")

    def query(self, table: str, conditions: Sequence[Eq], select: Sequence[str]) -> list[dict[str, Any]]:
        raise IdempiereClientError(f"No iDempiere client wired for {self._endpoint.base_url}")

    def create_record(self, table: str, fields: dict[str, Any]) -> int:
        raise IdempiereClientError(f"No iDempiere client wired for {self._endpoint.base_url}")

    def update_record(self, table: str, record_id: int, fields: dict[str, Any]) -> None:
        raise IdempiereClientError(f"No iDempiere client wired for {self._endpoint.base_url}")

    def execute_process(self, process_id: int, parameters: dict[str, Any]) -> dict[str, Any]:
        raise IdempiereClientError(f"No iDempiere client wired for {self._endpoint.base_url}")


@dataclass(frozen=True, slots=True)
class IdempiereCredentials:
    """One-step login parameters. base_url has no trailing slash, e.g.
    "https://idempiere:8443/api/v1"."""

    base_url: str
    username: str
    password: str
    client_id: int
    role_id: int
    organization_id: int
    warehouse_id: int | None = None
    language: str = "en_US"
    timeout_seconds: float = 10.0


class RestIdempiereClient:
    """Talks to a real iDempiere instance over its REST API (ADR-ERP-005).

    Not thread-safe: each instance holds one session's tokens. A per-request or
    per-thread client is the caller's responsibility, matching how
    modules/application/server.py opens a fresh Postgres connection per request.
    """

    _TOKEN_LIFETIME_SECONDS = 3600  # per spec: access token expires in 1 hour
    _REFRESH_SAFETY_MARGIN_SECONDS = 60

    def __init__(self, credentials: IdempiereCredentials) -> None:
        self._credentials = credentials
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._user_id: int | None = None
        self._token_expires_at: float = 0.0

    def get_record(self, table: str, record_id: int) -> dict[str, Any]:
        return self._call("GET", f"/models/{table}/{record_id}")

    def query(self, table: str, conditions: Sequence[Eq], select: Sequence[str]) -> list[dict[str, Any]]:
        """Every record matching the conditions, page by page ($filter/$select/$top/$skip of the REST plugin). A result
        larger than the safety cap is an error, never silently truncated: a partial list would be a wrong total."""
        if not _IDENTIFIER.fullmatch(table) or not all(_IDENTIFIER.fullmatch(c) for c in select):
            raise ValueError("table and select must be plain AD names")
        records: list[dict[str, Any]] = []
        while True:
            params = {"$filter": build_filter(conditions), "$select": ",".join(select), "$top": str(_PAGE_SIZE),
                      "$skip": str(len(records))}
            page = self._call("GET", f"/models/{table}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}")
            batch = page.get("records")
            if not isinstance(batch, list) or not all(isinstance(row, dict) for row in batch):
                raise IdempiereClientError(f"unexpected list response for {table}: no records array")
            records.extend(batch)
            if len(records) > _MAX_RECORDS:
                raise IdempiereClientError(f"{table} query exceeds {_MAX_RECORDS} records; refusing to truncate")
            total = page.get("row-count")
            if len(batch) < _PAGE_SIZE or (isinstance(total, int) and len(records) >= total):
                return records

    def create_record(self, table: str, fields: dict[str, Any]) -> int:
        created = self._call("POST", f"/models/{table}", body=fields)
        return int(created["id"])

    def update_record(self, table: str, record_id: int, fields: dict[str, Any]) -> None:
        self._call("PUT", f"/models/{table}/{record_id}", body=fields)

    def execute_process(self, process_id: int, parameters: dict[str, Any]) -> dict[str, Any]:
        """Execute an ERP business process rather than simulating document actions
        with model updates. The REST plugin accepts process parameters as a JSON
        object at this endpoint; callers remain responsible for using the process
        appropriate to the pinned iDempiere release."""
        return self._call("POST", f"/processes/{process_id}", body=parameters)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._ensure_token()
        try:
            return self._raw_request(method, path, body, token)
        except IdempiereAuthenticationError:
            # The token may have been invalidated server-side; retry once with a
            # fresh login rather than assuming every 401 means "give up".
            token = self._authenticate()
            return self._raw_request(method, path, body, token)

    def _raw_request(
        self, method: str, path: str, body: dict[str, Any] | None, token: str
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._credentials.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return self._send(request)

    def _ensure_token(self) -> str:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        if self._refresh_token is not None:
            try:
                return self._refresh()
            except IdempiereAuthenticationError:
                pass  # refresh token expired/reused; fall back to a full login
        return self._authenticate()

    def _authenticate(self) -> str:
        creds = self._credentials
        parameters = {
            "clientId": creds.client_id,
            "roleId": creds.role_id,
            "organizationId": creds.organization_id,
            "language": creds.language,
        }
        if creds.warehouse_id is not None:
            parameters["warehouseId"] = creds.warehouse_id
        body = {"userName": creds.username, "password": creds.password, "parameters": parameters}
        return self._store_token_response(self._auth_call("/auth/tokens", body))

    def _refresh(self) -> str:
        body = {
            "refresh_token": self._refresh_token,
            "clientId": self._credentials.client_id,
            "userId": self._user_id,
        }
        return self._store_token_response(self._auth_call("/auth/refresh", body))

    def _auth_call(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._credentials.base_url}{path}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            return self._send(request)
        except IdempiereApiError as exc:
            raise IdempiereAuthenticationError(f"{exc.title}: {exc.detail}") from exc

    def _store_token_response(self, response: dict[str, Any]) -> str:
        self._token = response["token"]
        self._refresh_token = response.get("refresh_token", self._refresh_token)
        if "userId" in response:
            self._user_id = response["userId"]
        self._token_expires_at = (
            time.monotonic() + self._TOKEN_LIFETIME_SECONDS - self._REFRESH_SAFETY_MARGIN_SECONDS
        )
        return self._token

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self._credentials.timeout_seconds) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            error = _read_error_body(exc)
            if exc.code == 401:
                raise IdempiereAuthenticationError(error.get("detail", "unauthorized")) from exc
            raise IdempiereApiError(exc.code, error.get("title", "Error"), error.get("detail", "")) from exc
        except urllib.error.URLError as exc:
            raise IdempiereClientError(f"Could not reach {request.full_url}: {exc}") from exc


def _read_error_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """iDempiere's ErrorResponse shape is {title, status, detail}; tolerate anything
    else (a proxy's own HTML error page, an empty body) rather than raising through it.
    """
    try:
        return json.loads(exc.read())
    except (json.JSONDecodeError, ValueError):
        return {}
