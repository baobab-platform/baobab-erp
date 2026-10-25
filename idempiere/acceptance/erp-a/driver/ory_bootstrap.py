#!/usr/bin/env python3
"""DEV-09 disposable real Ory issuance + current CP consumption.

Uses *IAM-owned* pinned source configuration and Ory images. No stored tokens,
provider secrets, raw HTTP bodies or privileged credentials in evidence.
The synthetic CP human administrator issuer is a separate fixture.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CLIENT = "baobab-erp-legal-actor-assessor-staging"
SCOPES = ("context:resolve", "legal-actor:assess", "documentary:restriction-assess",
          "erp-posting-authority:resolve")
HYDRA_ADMIN = "http://127.0.0.1:18013"
HYDRA_PUBLIC = "http://127.0.0.1:18015"
KRATOS_ADMIN = "http://127.0.0.1:18014"
CP = "http://127.0.0.1:18092"
ISSUER = "https://hydra.gated.test"


def require(ok: bool, why: str) -> None:
    if not ok:
        raise RuntimeError("DEV09_ORY_" + why)


def http(method: str, url: str, body=None, *, form=False, token=None, timeout=8):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        headers["Content-Type"] = ("application/x-www-form-urlencoded" if form
                                   else "application/json")
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data, headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            status, raw = r.status, r.read(65537)
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read(65537)
    require(len(raw) <= 65536, "UNBOUNDED_RESPONSE")
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


def await_up(url: str) -> None:
    for _ in range(80):
        try:
            status, _ = http("GET", url, timeout=3)
            if status == 200:
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(2)
    raise RuntimeError("DEV09_ORY_PROVIDER_NOT_READY")


def prepare(run: Path, iam: Path, pinned_sha: str) -> None:
    # Sources are immutable and operator pinned; do not invent OAuth policy.
    sha = subprocess.run(["git", "-C", str(iam), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    require(sha == pinned_sha and len(sha) == 40, "IAM_SOURCE_PIN")
    source = iam / "config/ory"
    hydra = (source / "hydra/hydra.yml").read_text()
    kratos = (source / "kratos/kratos.yml").read_text()
    require("  access_token: jwt" in hydra and "  expose_internal_errors: false" in hydra,
            "IAM_CONFIG_DRIFT")
    require("local_dev_only_hydra_system_secret_change_me" in hydra
            and "local_dev_only_pairwise_salt_change_me" in hydra, "IAM_SECRET_MARKERS")
    hydra = hydra.replace("http://127.0.0.1:4444", ISSUER)
    hydra = hydra.replace("http://127.0.0.1:3000", "https://rp.gated.test")
    hydra = hydra.replace("local_dev_only_hydra_system_secret_change_me",
                          os.environ["ORY_SYSTEM_SECRET"])
    hydra = hydra.replace("local_dev_only_pairwise_salt_change_me",
                          os.environ["ORY_HOOK_SECRET"])
    hydra = hydra.replace("  access_token: jwt",
                          "  access_token: jwt\n  jwt:\n    scope_claim: string")
    hydra = hydra.replace("  expose_internal_errors: false",
                          "  expose_internal_errors: false\n"
                          "  allowed_top_level_claims: [actor_type, azp]\n"
                          "  mirror_top_level_claims: false\n"
                          "  token_hook:\n"
                          "    url: http://issuer:8000/_token_hook\n"
                          "    auth:\n"
                          "      type: api_key\n"
                          "      config:\n"
                          "        in: header\n"
                          "        name: X-ERP-A-Hook-Key\n"
                          "        value: " + os.environ["ORY_HOOK_SECRET"])
    hydra += "\nttl:\n  access_token: 2m\n"
    kratos = kratos.replace("http://127.0.0.1:4433/", "https://kratos.gated.test/")
    kratos = kratos.replace("http://127.0.0.1:4434/", "http://kratos:4434/")
    kratos = kratos.replace("http://127.0.0.1:4455", "https://rp.gated.test")
    kratos = kratos.replace("http://127.0.0.1:3000", "https://rp.gated.test")
    kratos = kratos.replace("local_dev_only_cookie_secret_32b",
                            os.environ["ORY_SYSTEM_SECRET"][:32])
    kratos = kratos.replace("local_dev_only_cipher_secret_32b",
                            os.environ["ORY_SYSTEM_SECRET"][:32])
    for folder in ("hydra", "kratos"):
        (run / "ory" / folder).mkdir(parents=True, mode=0o755, exist_ok=False)
    for p, data in [
        (run / "ory/hydra/hydra.yml", hydra),
        (run / "ory/kratos/kratos.yml", kratos),
    ]:
        p.write_text(data)
        p.chmod(0o644)  # private owning run directory, read-only container mount
    (run / "ory/kratos/identity.schema.json").write_bytes(
        (source / "kratos/identity.schema.json").read_bytes())
    (run / "ory/kratos/identity.schema.json").chmod(0o644)


def provision(run: Path, out: Path, iam_sha: str) -> None:
    await_up(HYDRA_PUBLIC + "/.well-known/openid-configuration")
    await_up(KRATOS_ADMIN + "/admin/health/ready")
    status, discovery = http("GET", HYDRA_PUBLIC + "/.well-known/openid-configuration")
    require(status == 200 and discovery.get("issuer") == ISSUER, "WRONG_NATIVE_ISSUER")
    secret = os.environ["ERP_WORKLOAD_SECRET"]
    client = {
        "client_id": CLIENT, "client_secret": secret,
        "grant_types": ["client_credentials"], "response_types": [],
        "scope": " ".join(SCOPES), "audience": ["baobab-control-plane"],
        "token_endpoint_auth_method": "client_secret_post",
        "client_credentials_grant_access_token_lifespan": "120s",
        "metadata": {"evidence": "dev09-synthetic-erp-acceptance", "environment": "integration"}
    }
    status, created = http("POST", HYDRA_ADMIN + "/admin/clients", client)
    require(status == 201 and created.get("client_id") == CLIENT, "HYDRA_CREATE")
    status, observed = http("GET", HYDRA_ADMIN + "/admin/clients/" + CLIENT)
    require(status == 200 and observed["client_id"] == CLIENT
            and observed["grant_types"] == ["client_credentials"]
            and observed["audience"] == ["baobab-control-plane"]
            and set(observed["scope"].split()) == set(SCOPES), "HYDRA_READBACK")
    # Kratos owns the real human identity records. Those synthetic humans
    # DO NOT authorize CP administrators in this ERP-A test harness.
    observed_subjects = []
    for role in ("maker", "checker"):
        identity = {
            "schema_id": "default",
            "traits": {"email": "dev09-" + role + "-" + uuid.uuid4().hex + "@example.invalid"},
            "credentials": {"password": {"config": {"password": uuid.uuid4().hex
                                                    + uuid.uuid4().hex}}},
        }
        status, created = http("POST", KRATOS_ADMIN + "/admin/identities", identity)
        require(status == 201 and created["state"] == "active", "KRATOS_CREATE")
        status, got = http("GET", KRATOS_ADMIN + "/admin/identities/" + created["id"])
        require(status == 200 and got["id"] == created["id"]
                and got["state"] == "active"
                and got["traits"]["email"] == identity["traits"]["email"], "KRATOS_READBACK")
        observed_subjects.append(created["id"])
    require(len(set(observed_subjects)) == 2, "DISTINCT_KRATOS_HUMANS")
    (run / "ory-native-observed").write_text("ok\n")
    (out / "dev09-ory-provision.json").write_text(json.dumps({
        "schema": "dev09-ory-provision.v1", "iam_source_sha": iam_sha,
        "hydra_native_client_readback": True, "hydra_client_credentials_only": True,
        "kratos_distinct_human_records": True,
        "cp_admin_authority_from_kratos": False,
        "protected_qualified": False}, indent=2) + "\n")


def consume(run: Path, out: Path) -> None:
    require((run / "ory-native-observed").read_text() == "ok\n", "UNPROVISIONED")
    state = json.loads((run / "cp-seed.json").read_text())
    status, body = http("POST", HYDRA_PUBLIC + "/oauth2/token", {
        "grant_type": "client_credentials", "client_id": CLIENT,
        "client_secret": os.environ["ERP_WORKLOAD_SECRET"],
        "scope": " ".join(SCOPES), "audience": "baobab-control-plane"
    }, form=True)
    require(status == 200 and isinstance(body.get("access_token"), str),
            "HYDRA_TOKEN")
    token = body["access_token"]
    require(body.get("token_type", "").lower() == "bearer", "HYDRA_TOKEN_TYPE")
    # CP, not the issuer or this test driver, resolves actual tenant/org context.
    context = {"tenant_id": state["tenant"], "organisation_id": state["organisation"],
               "country_code": state["market"]}
    status, response = http("POST", CP + "/v1/platform-context/resolve", context, token=token)
    require(status == 200 and response.get("tenant_id") == state["tenant"]
            and response.get("organisation_id") == state["organisation"]
            and response.get("country_code") == state["market"], "CP_CURRENT_AUTHORITY")
    # Possessing a valid native token is not authority to another operating org.
    attempted = dict(context, organisation_id=str(uuid.uuid4()))
    status, _ = http("POST", CP + "/v1/platform-context/resolve", attempted, token=token)
    require(status in (400, 401, 403, 404, 409, 422), "CROSS_ORG_DENIAL")
    (out / "dev09-ory-consumption.json").write_text(json.dumps({
        "schema": "dev09-ory-consumption.v1",
        "real_hydra_issued": True, "cp_current_tenant_org_context": True,
        "wrong_org_denied": True, "legal_actor_decision_tested_by_native_erp": True,
        "independent_provider_qualified": False, "protected_qualified": False,
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "provision", "consume"])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--iam", type=Path)
    parser.add_argument("--iam-sha")
    args = parser.parse_args()
    if args.phase == "prepare":
        require(args.iam is not None and args.iam_sha is not None, "PIN_REQUIRED")
        prepare(args.run, args.iam, args.iam_sha)
    elif args.phase == "provision":
        require(args.iam_sha is not None, "PIN_REQUIRED")
        provision(args.run, args.out, args.iam_sha)
    else:
        consume(args.run, args.out)
