"""ERP-A harness helpers: HTTP, the databases, the iDempiere driver protocol
and the evidence record. Standard library only.

Every call is to a harness-published loopback port; iDempiere itself reaches CP
and IAM only over TLS through the edge.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CP = "http://127.0.0.1:18092"
ISSUER = "http://127.0.0.1:18010"
PROJECT = os.environ.get("ERP_A_PROJECT", "baobab-gate-d-erp-a")


class Response:
    def __init__(self, status: int, body, headers: dict, target: str = ""):
        self.status, self.body, self.headers, self.target = status, body, headers, target

    def __repr__(self) -> str:
        return f"<{self.target} {self.status} {json.dumps(self.body)[:400]}>"


def call(method: str, url: str, body=None, headers: dict | None = None, timeout: float = 60) -> Response:
    data, hdrs = None, dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            raw, status, rh = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, status, rh = e.read(), e.code, dict(e.headers)
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode(errors="replace")
    return Response(status, parsed, {k.lower(): v for k, v in rh.items()}, f"{method} {url.split('?')[0]}")


class Compose:
    def __init__(self, file: str):
        self.base = ["docker", "compose", "-f", file, "-p", PROJECT]

    def run(self, *args: str, check: bool = True) -> str:
        p = subprocess.run(self.base + list(args), capture_output=True, text=True, env=dict(os.environ))
        if check and p.returncode != 0:
            raise RuntimeError(f"compose {' '.join(args)} failed: {p.stderr[-2000:]}")
        return p.stdout

    def psql(self, service: str, user: str, db: str, statement: str, check: bool = True,
             quiet: bool = True) -> subprocess.CompletedProcess:
        p = subprocess.run(self.base + ["exec", "-T", service, "psql", "-X"] + (["-q"] if quiet else []) + ["-At", "-F", "\t",
                                        "-v", "ON_ERROR_STOP=1", "-U", user, "-d", db],
                           input=statement, capture_output=True, text=True, env=dict(os.environ))
        if check and p.returncode != 0:
            raise RuntimeError(f"psql on {service} failed: {p.stderr[-2000:]}")
        return p

    def sql(self, service: str, user: str, db: str, statement: str) -> list[list[str]]:
        out = self.psql(service, user, db, statement).stdout
        return [line.split("\t") for line in out.splitlines() if line]

    def scalar(self, service: str, user: str, db: str, statement: str) -> str:
        rows = self.sql(service, user, db, statement)
        return rows[-1][0] if rows and rows[-1] else ""


class Erp:
    """iDempiere's database (as its own runtime role) and the driver bundle's
    file protocol: requests/<name>.properties -> results/<name>.properties."""

    def __init__(self, compose: Compose, run_dir: str):
        self.c = compose
        self.dir = Path(run_dir) / "gate-d"

    def sql(self, statement: str) -> str:
        return self.c.scalar("erpdb", "adempiere", "idempiere", "SET search_path = adempiere, public;\n" + statement)

    def bypass(self, statement: str) -> str:
        """One statement in its own explicit transaction as the iDempiere runtime
        role, outside the JVM: the COMMIT fence is the only thing in the way."""
        p = self.c.psql("erpdb", "adempiere", "idempiere",
                        f"BEGIN;\n{statement};\nCOMMIT;", check=False, quiet=False)
        return (p.stdout + p.stderr).strip()

    def request(self, name: str, timeout: int = 180, **props) -> dict:
        requests, results = self.dir / "requests", self.dir / "results"
        (results / f"{name}.properties").unlink(missing_ok=True)
        tmp = requests / f"{name}.tmp"
        tmp.write_text("".join(f"{k}={v}\n" for k, v in props.items()))
        tmp.rename(requests / f"{name}.properties")
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = results / f"{name}.properties"
            if result.exists():
                out = {}
                for line in result.read_text().splitlines():
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        out[k] = v.replace("\\:", ":").replace("\\=", "=").replace("\\ ", " ")
                return out
            time.sleep(0.5)
        return {"driver_error": "timeout"}

    def held(self, marker: str, timeout: int = 120) -> str:
        path = self.dir / "held" / marker
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return path.read_text().strip()
            time.sleep(0.2)
        return ""


class Evidence:
    def __init__(self, out_dir: str):
        self.out = Path(out_dir)
        self.notes: list[dict] = []
        self.scenarios: list[dict] = []

    def note(self, kind: str, data: dict) -> None:
        self.notes.append({"kind": kind, **data})

    def scenario(self, sid: str, title: str, ok: bool, detail: str = "") -> bool:
        self.scenarios.append({"id": sid, "title": title, "result": "PASS" if ok else "FAIL", "detail": detail})
        line = f"{'PASS' if ok else 'FAIL'}  {sid} {title}" + (f": {detail}" if detail and not ok else "")
        print(line, flush=True)
        with open(self.out / "erp-a-report.txt", "a") as f:
            f.write(line + "\n")
        return ok

    def failures(self) -> int:
        return sum(1 for s in self.scenarios if s["result"] != "PASS")


def key() -> str:
    return str(uuid.uuid4())
