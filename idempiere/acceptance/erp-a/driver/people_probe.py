#!/usr/bin/env python3
"""ERP's actual People selector against real Hydra-signed CP HTTPS.

Runs ONLY in the disposable ERP-A Compose People profile. The input is a
fixture intent, never an employer/provider claim sent to CP. No token, HTTP
body or worker data is printed or written to report artifacts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from people.providers.selection import CPProviderSelector, ProviderSelectionDenied


ROOT = Path("/run/people")
CLIENT = "baobab-erp-people-dev-witness"


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


def main() -> None:
    if os.environ.get("BAOBAB_ENVIRONMENT") != "integration":
        raise SystemExit("People witness is integration-only")
    case = json.loads((ROOT / "case.json").read_text(encoding="utf-8"))
    if set(case) != {"name", "tenant_id", "legal_employer_id", "jurisdiction",
                     "context_id", "token_file", "expect"}:
        raise SystemExit("invalid closed People witness case")
    if case["expect"] not in ("allow", "deny"):
        raise SystemExit("invalid witness expectation")
    selector = CPProviderSelector("https://cp.gated.test", IssuedWorkloadToken(case["token_file"]))
    allowed = False
    result = None
    try:
        result = selector.resolve(
            context_id=case["context_id"],
            correlation_id=str(uuid.uuid4()),
            capability_key="payroll.run.read",
            tenant_id=case["tenant_id"],
            legal_employer_id=case["legal_employer_id"],
            jurisdiction=case["jurisdiction"],
            now=datetime.now(timezone.utc),
        )
        allowed = True
    except ProviderSelectionDenied:
        pass
    if allowed != (case["expect"] == "allow"):
        raise SystemExit("PEOPLE_WITNESS_UNEXPECTED_DECISION:" + case["name"])
    out = {"case": case["name"], "accepted": allowed}
    if allowed:
        out.update({"provider_id": result.provider_id, "binding_id": result.binding_id,
                    "binding_revision": result.binding_revision,
                    "employer": result.legal_employer_id,
                    "source_of_record": result.source_of_record})
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
