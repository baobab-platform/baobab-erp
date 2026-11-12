#!/usr/bin/env python3
"""Development-only ERP People selector against actual Ory/CP HTTPS.

The witness fails if CP is unavailable or a non-denial HTTP response is
returned. Synthetic policy refusals cannot be conflated with network failure.
No tokens, worker data, raw HTTP bodies or provider secrets enter evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import ssl
import uuid
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from people.providers.selection import (
    CPProviderSelector, ProviderSelectionDenied, _NoRedirect,
)

ROOT = Path("/run/people")


class IssuedWorkloadToken:
    def __init__(self, name: str):
        if name not in ("issued-token", "reduced-token"):
            raise RuntimeError("unreviewed People token source")
        self.name = name

    def access_token(self, audience: str, scopes: tuple[str, ...]) -> str:
        if audience != "baobab-control-plane" or scopes != (
            "context:resolve", "people:provider:read"
        ):
            raise RuntimeError("ERP requested unregistered People authority")
        token = (ROOT / self.name).read_text(encoding="ascii").strip()
        if len(token) < 100 or any(c.isspace() for c in token):
            raise RuntimeError("no Ory-issued test credential")
        return token


class ObservedCPTransport:
    """Same no-proxy, TLS-validated, no-redirect boundary as ERP adapter.

    Only 401/403 are observed as CP refusals. Every outage, timeout,
    unexpected HTTP status or malformed success fails the test, not a
    denial PASS. The selected ERP adapter still verifies the full body.
    """
    def __init__(self):
        self.status: int | None = None
        self.opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirect(),
        )

    def __call__(self, url: str, data: bytes, token: str) -> bytes:
        if not url.startswith("https://cp.gated.test/") or len(data) > 8192:
            raise RuntimeError("untrusted People probe request")
        if not token or any(c.isspace() for c in token):
            raise RuntimeError("invalid Ory token")
        request = Request(url, data=data, headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json", "Accept": "application/json",
        }, method="POST")
        try:
            with self.opener.open(request, timeout=7) as response:
                self.status = response.status
                if self.status != 200:
                    raise RuntimeError("unexpected CP success status")
                if response.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                    raise RuntimeError("unexpected CP success content type")
                raw = response.read(32769)
                if len(raw) > 32768:
                    raise RuntimeError("unbounded CP selection response")
                return raw
        except HTTPError as err:
            self.status = err.code
            if err.code not in (401, 403):
                raise RuntimeError("CP returned non-denial error") from err
            raise ProviderSelectionDenied("CP refused current provider authority") from err


def main() -> None:
    if os.environ.get("BAOBAB_ENVIRONMENT") != "integration":
        raise SystemExit("People witness is integration-only")
    case = json.loads((ROOT / "case.json").read_text(encoding="utf-8"))
    if set(case) != {"name", "tenant_id", "legal_employer_id", "jurisdiction",
                     "context_id", "token_file", "expect", "cp_http_statuses"}:
        raise SystemExit("invalid closed People witness case")
    if (case["expect"] not in ("allow", "deny")
            or not isinstance(case["cp_http_statuses"], list)
            or not case["cp_http_statuses"]
            or any(type(s) is not int or s not in (200, 401, 403)
                   for s in case["cp_http_statuses"])):
        raise SystemExit("invalid expected CP decision")
    transport = ObservedCPTransport()
    selector = CPProviderSelector(
        "https://cp.gated.test", IssuedWorkloadToken(case["token_file"]), transport
    )
    allowed = False
    result = None
    try:
        result = selector.resolve(
            context_id=case["context_id"], correlation_id=str(uuid.uuid4()),
            capability_key="payroll.run.read", tenant_id=case["tenant_id"],
            legal_employer_id=case["legal_employer_id"],
            jurisdiction=case["jurisdiction"], now=datetime.now(timezone.utc),
        )
        allowed = True
    except ProviderSelectionDenied:
        pass
    if allowed != (case["expect"] == "allow") or transport.status not in case["cp_http_statuses"]:
        raise SystemExit("PEOPLE_WITNESS_UNEXPECTED_DECISION:" + case["name"])
    out = {"case": case["name"], "accepted": allowed, "cp_http_status": transport.status}
    if allowed:
        out.update({"provider_id": result.provider_id, "binding_id": result.binding_id,
                    "binding_revision": result.binding_revision,
                    "employer": result.legal_employer_id,
                    "source_of_record": result.source_of_record})
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
