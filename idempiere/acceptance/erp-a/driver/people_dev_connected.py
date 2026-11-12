#!/usr/bin/env python3
"""Connected, strictly disposable IAM/Hydra -> CP/PG17 -> ERP People witness.

Uses the already running ERP-A network, actual Ory client-credentials issuer,
the merged CP release binary, HTTPS with a throwaway CA, and ERP's own
CPProviderSelector. No employee data, payroll calculations, or GL effects.
A synthetic ACTIVE capability/certification is created ONLY in the fresh CP
integration database; Shared's real People capability stays DRAFT.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import uuid

from erpalib import Compose
from ory_bootstrap import CP, HYDRA_ADMIN, HYDRA_PUBLIC, http, require

CLIENT = "baobab-erp-people-dev-witness"
SCOPES = ("context:resolve", "people:provider:read")
CAPABILITY = "payroll.run.read"
REGISTRY = "people-dev-witness-" + uuid.uuid4().hex[:12]


def check(condition: bool, label: str) -> None:
    if not condition:
        raise RuntimeError("PEOPLE_DEV_WITNESS_" + label)


def safe(value: str, grammar: str) -> str:
    check(isinstance(value, str) and re.fullmatch(grammar, value) is not None, "INVALID_FIXTURE_ID")
    return value


def scalar(compose: Compose, statement: str) -> str:
    return compose.scalar("cpdb", "controlplane", "controlplane", statement)


def rows(compose: Compose, statement: str) -> list[list[str]]:
    return compose.sql("cpdb", "controlplane", "controlplane", statement)


def provision_ory(secret: str, tenant_state: dict) -> tuple[str, str]:
    expected = {"client_id": CLIENT, "client_secret": secret,
        "grant_types": ["client_credentials"], "response_types": [],
        "scope": " ".join(SCOPES), "audience": ["baobab-control-plane"],
        "token_endpoint_auth_method": "client_secret_post",
        "client_credentials_grant_access_token_lifespan": "120s",
        "metadata": {"evidence": "disposable-people-dev-witness", "environment": "development"}}
    status, created = http("POST", HYDRA_ADMIN + "/admin/clients", expected)
    check(status == 201 and created.get("client_id") == CLIENT, "HYDRA_REGISTRATION")
    status, observed = http("GET", HYDRA_ADMIN + "/admin/clients/" + CLIENT)
    check(status == 200 and observed["grant_types"] == ["client_credentials"]
          and observed["audience"] == ["baobab-control-plane"]
          and set(observed["scope"].split()) == set(SCOPES), "HYDRA_INDEPENDENT_READBACK")

    def issue(scope: str) -> str:
        status, body = http("POST", HYDRA_PUBLIC + "/oauth2/token", {
            "grant_type": "client_credentials", "client_id": CLIENT,
            "client_secret": secret, "audience": "baobab-control-plane", "scope": scope,
        }, form=True)
        check(status == 200 and isinstance(body.get("access_token"), str)
              and body.get("token_type", "").lower() == "bearer", "HYDRA_SIGNED_TOKEN")
        return body["access_token"]

    full = issue(" ".join(SCOPES))
    limited = issue("context:resolve")
    # A held workload must not silently gain a foreign audience.
    status, _ = http("POST", HYDRA_PUBLIC + "/oauth2/token", {
        "grant_type": "client_credentials", "client_id": CLIENT,
        "client_secret": secret, "audience": "baobab-erp", "scope": " ".join(SCOPES),
    }, form=True)
    if status == 200:
        check(isinstance(_.get("access_token"), str), "FOREIGN_AUDIENCE_TOKEN_MISSING")
        refused, _ = http("POST", CP + "/v1/platform-context/resolve", {
            "tenant_id": tenant_state["tenant"],
            "organisation_id": tenant_state["organisation"],
            "country_code": tenant_state["market"],
        }, token=_["access_token"])
        check(refused in (401, 403), "FOREIGN_AUDIENCE_CP_ADMITTED")
    else:
        check(status in (400, 401, 403), "FOREIGN_AUDIENCE_ISSUED")
    return full, limited


def seed_choice(c: Compose, state: dict) -> dict[str, str]:
    employer = safe(state["second"]["legal_entity"], r"[A-Z][A-Z0-9-]*")
    tenant = safe(state["second"]["tenant"], r"tn_[a-z0-9]+")
    maker = str(uuid.UUID(state["second"]["maker"]))
    checker = str(uuid.UUID(state["second"]["checker"]))
    check(maker != checker, "SELF_APPROVAL")
    # Require projected canonical People DRAFT before the disposable
    # capability projection may be overridden. Never update Shared or a
    # persistent Control Plane, and never create live provider credentials.
    check(scalar(c, "SELECT status FROM capability.capability WHERE code='payroll.run.read'") == "DRAFT",
          "CANONICAL_DRAFT_PRECONDITION")
    engine, instance, provider, scope, binding, release, cert, grant = (
        str(uuid.uuid4()) for _ in range(8))
    cap = scalar(c, "SELECT capability_id::text FROM capability.capability WHERE code='payroll.run.read'")
    check(bool(cap), "CANONICAL_CAPABILITY_MISSING")
    # The synthetic ACTIVE status exists only for the lifetime of this
    # disposable CP DB, because the real canonical catalogue is DRAFT.
    sql = f"""
BEGIN;
UPDATE capability.capability SET status='ACTIVE' WHERE capability_id='{cap}'::uuid AND status='DRAFT';
INSERT INTO topology.engine (engine_id,code,name)
 VALUES ('{engine}'::uuid,'{REGISTRY}','People dev-only witness');
INSERT INTO topology.engine_instance(engine_instance_id,engine_id,region,environment,status)
 VALUES ('{instance}'::uuid,'{engine}'::uuid,'af-south-1','integration','ACTIVE');
INSERT INTO capability.capability_provider
 (provider_id,provider_key,name,provider_type,engine_id,status,service_reference,invocation_protocol)
 VALUES ('{provider}'::uuid,'{REGISTRY}.external','Disposable external provider','EXTERNAL_SERVICE',
         '{engine}'::uuid,'ACTIVE','service://people-dev-witness/payroll','http');
INSERT INTO capability.capability_scope( scope_id,tenant_id,legal_entity_id,jurisdiction )
 VALUES ('{scope}'::uuid,'{tenant}','{employer}','ZA');
INSERT INTO capability.provider_capability_support(provider_id,capability_id,contract_versions,status)
 VALUES ('{provider}'::uuid,'{cap}'::uuid,ARRAY[1],'ACTIVE');
INSERT INTO capability.capability_binding
 (id,capability_id,engine_instance_id,scope_id,provider_id,binding_mode,status,contract_version,effective_from,version)
 VALUES ('{binding}'::uuid,'{cap}'::uuid,'{instance}'::uuid,'{scope}'::uuid,
         '{provider}'::uuid,'PRIMARY','ACTIVE','1',now()-interval '2 minutes',1);
INSERT INTO capability.capability_grant
 (grant_id,tenant_id,capability_id,scope_id,source,status,effective_from)
 VALUES ('{grant}'::uuid,'{tenant}','{cap}'::uuid,'{scope}'::uuid,
         'PLATFORM_BASELINE','ACTIVE',now()-interval '2 minutes');
INSERT INTO topology.engine_release
 (engine_release_id,engine_id,release_version,source_revision,declaration_digest,content_digest,status,
  recorded_by,recorded_at,reason,status_changed_by,status_changed_at,status_reason)
 VALUES ('{release}'::uuid,'{engine}'::uuid,'1.0.0',repeat('a',40),
   'sha256:'||repeat('b',64),'sha256:'||repeat('c',64),'APPROVED',
   'people-dev-fixture',now(),'Disposable test only',
   'people-dev-reviewer',now(),'Development fixture');
INSERT INTO topology.engine_release_provider_support
 (engine_release_id,ordinal,provider_key,capability_key,contract_versions)
 VALUES ('{release}'::uuid,0,'{REGISTRY}.external','payroll.run.read',ARRAY[1]);
INSERT INTO capability.provider_capability_certification
 (certification_id,provider_id,capability_id,contract_version,engine_release_id,
  qualification_profile,evidence,request_digest,status,certified_by,certified_at,reason)
 VALUES ('{cert}'::uuid,'{provider}'::uuid,'{cap}'::uuid,1,'{release}'::uuid,
   'people-dev-synthetic-fixture','[{{"dev_only":true}}]'::jsonb,'sha256:'||repeat('d',64),
   'CERTIFIED','synthetic-pg17-reviewer',now(),'NOT statutory or real provider certification');
INSERT INTO capability.people_provider_choice
 (tenant_id,legal_employer_id,jurisdiction,capability_key,binding_id,provider_id,binding_revision,
  certification_id,source_of_record,status,effective_from,proposed_by,approved_by,approved_at,choice_evidence_ref)
 VALUES ('{tenant}','{employer}','ZA','payroll.run.read','{binding}'::uuid,'{provider}'::uuid,
         1,'{cert}'::uuid,'EXTERNAL','ACTIVE',now()-interval '2 minutes',
         '{maker}'::uuid,'{checker}'::uuid,now(),'people-dev/disposable-fixture');
COMMIT;
"""
    c.sql("cpdb", "controlplane", "controlplane", sql)
    check(scalar(c, f"""SELECT count(*) FROM capability.people_provider_choice
                         WHERE tenant_id='{tenant}' AND legal_employer_id='{employer}'
                         AND binding_id='{binding}'::uuid AND provider_id='{provider}'::uuid""") == "1",
          "CHOICE_NOT_PERSISTED")
    return dict(tenant=tenant, employer=employer, capability=cap, provider=provider,
                binding=binding, cert=cert, grant=grant)


def context_for(token: str, profile: dict) -> str:
    status, response = http("POST", CP + "/v1/platform-context/resolve", {
        "tenant_id": profile["tenant"], "organisation_id": profile["organisation"],
        "country_code": profile["market"],
    }, token=token)
    check(status == 200 and response.get("tenant_id") == profile["tenant"]
          and isinstance(response.get("context_id"), str), "CP_AUTHENTIC_CONTEXT")
    return response["context_id"]


def run_case(c: Compose, root: Path, *, name: str, context_id: str,
             tenant: str, employer: str, jurisdiction: str, expect: str,
             token_file: str = "issued-token", cp_http_statuses: tuple[int, ...] = (200,)) -> dict:
    case = {"name": name, "context_id": context_id, "tenant_id": tenant,
            "legal_employer_id": employer, "jurisdiction": jurisdiction,
            "expect": expect, "token_file": token_file,
            "cp_http_statuses": list(cp_http_statuses)}
    (root / "case.json").write_text(json.dumps(case), encoding="utf-8")
    (root / "case.json").chmod(0o644)
    output = c.run("--profile", "people", "run", "--rm", "--no-deps", "-T", "people-probe")
    try:
        result = json.loads(output.splitlines()[-1])
    except (ValueError, IndexError) as error:
        raise RuntimeError("PEOPLE_DEV_UNREADABLE_ERP_CONSUMER") from error
    check(result.get("case") == name and result.get("accepted") == (expect == "allow"),
          "ERP_CONSUMER_MISMATCH_" + name)
    return result


def verify(c: Compose, fixture: dict, context_id: str, expected_resolutions: int) -> None:
    tenant, employer = fixture["tenant"], fixture["employer"]
    # This SQL query is deliberately independent from both the CP selector's
    # SQL implementation and the Python consumer's HTTP response.
    facts = rows(c, f"""
SELECT choice.binding_id::text, choice.provider_id::text, choice.status,
       cert.status, cb.version::text, grant.status,
       cap.status, count(DISTINCT r.resolution_id)::text,
       count(DISTINCT CASE WHEN r.decision='RESOLVED' THEN r.resolution_id END)::text
FROM capability.people_provider_choice choice
JOIN capability.provider_capability_certification cert ON cert.certification_id=choice.certification_id
JOIN capability.capability_binding cb ON cb.id=choice.binding_id
JOIN capability.capability cap ON cap.capability_id=cb.capability_id
JOIN capability.capability_grant grant ON grant.scope_id=cb.scope_id AND grant.capability_id=cap.capability_id
LEFT JOIN capability.capability_resolution r ON r.tenant_id=choice.tenant_id
  AND r.context_id='{context_id}' AND r.capability_key='payroll.run.read'
WHERE choice.tenant_id='{tenant}' AND choice.legal_employer_id='{employer}'
GROUP BY choice.binding_id, choice.provider_id, choice.status,cert.status,cb.version,grant.status,cap.status;
""")
    check(len(facts) == 1 and facts[0][0] == fixture["binding"]
          and facts[0][1] == fixture["provider"]
          and facts[0][2] == "ACTIVE" and facts[0][4] == "1"
          and facts[0][5] == "ACTIVE"
          and int(facts[0][7]) == expected_resolutions
          and int(facts[0][8]) == expected_resolutions, "INDEPENDENT_PG17_READBACK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compose", required=True)
    args = parser.parse_args()
    check(os.environ.get("BAOBAB_ENVIRONMENT") == "integration"
          and os.environ.get("PEOPLE_DEV_CONNECTED") == "true", "PROTECTED_ENVIRONMENT")
    c = Compose(args.compose)
    state = json.loads((args.run / "cp-seed.json").read_text())
    root = args.run / "people-secret"
    secret = (root / "workload-secret").read_text().strip()
    token, reduced = provision_ory(secret, state["second"])
    # These token files are never copied to GitHub Actions artifacts or logs.
    for name, value in (("issued-token", token), ("reduced-token", reduced)):
        (root / name).write_text(value)
        (root / name).chmod(0o644)
    first = state["second"]  # ZA employer is positive; US employer is foreign.
    fixture = seed_choice(c, state)
    context_id = context_for(token, first)
    foreign_context_id = context_for(token, state)
    actual = rows(c, f"""SELECT tenant_id,legal_entity_id,jurisdiction,authority_purpose
                           FROM context.resolved_context WHERE context_id='{context_id}'""")
    check(len(actual) == 1 and actual[0] == [fixture["tenant"], fixture["employer"],
                                           "ZA", "RUNTIME"], "CONTEXT_DB_LINEAGE")
    check(scalar(c, f"""SELECT count(*) FROM capability.people_provider_choice
                          WHERE tenant_id='{fixture["tenant"]}' AND legal_employer_id='{state["legal_entity"]}'""") == "0",
          "CROSS_EMPLOYER_DB_ISOLATION")
    results = []
    def case(**kw):
        results.append(run_case(c, root, **kw))
    allowed = dict(context_id=context_id, tenant=fixture["tenant"],
                   employer=fixture["employer"], jurisdiction="ZA")
    case(name="PPL-01-real-hydra-cp-erp-allow", expect="allow", **allowed)
    case(name="PPL-02-same-token-context-replay", expect="allow", **allowed)
    for result in results:
        check(result["provider_id"] == "provider_" + fixture["provider"].replace("-", "")
              and result["binding_id"] == "bind_" + fixture["binding"].replace("-", "")
              and result["employer"] == fixture["employer"], "SELECTED_PROVIDER_MISMATCH")
    verify(c, fixture, context_id, 2)
    case(name="PPL-03-cross-tenant-deny", context_id=foreign_context_id,
         tenant=state["tenant"], employer=state["legal_entity"],
         jurisdiction=state["market"], expect="deny", cp_http_statuses=(403,))
    # ERP expected-employer verification independently rejects a valid CP
    # selection for a *different* employer, even with the same bearer.
    case(name="PPL-04-cross-employer-deny", context_id=context_id,
         tenant=fixture["tenant"], employer=state["legal_entity"],
         jurisdiction="ZA", expect="deny", cp_http_statuses=(200,))
    case(name="PPL-05-reduced-issuer-scope-deny", expect="deny",
         token_file="reduced-token", cp_http_statuses=(401, 403), **allowed)
    verify(c, fixture, context_id, 3)
    check(scalar(c, f"SELECT count(*) FROM capability.people_provider_choice WHERE tenant_id='{fixture['tenant']}'") == "1",
          "REPLAY_DUPLICATED_CHOICE")
    c.sql("cpdb", "controlplane", "controlplane", f"""
UPDATE capability.provider_capability_certification
 SET status='REVOKED', revoked_by='synthetic-pg17-reviewer',revoked_at=now(),
     revocation_reason='Development witness: immediate revocation refusal'
 WHERE certification_id='{fixture['cert']}'::uuid;""")
    check(scalar(c, f"""SELECT status FROM capability.provider_capability_certification
                         WHERE certification_id='{fixture["cert"]}'::uuid""") == "REVOKED",
          "CERT_REVOCATION_NOT_DURABLE")
    # Cert revocation must cause refusal while the ORIGINAL bearer remains
    # accepted by CP for an unrelated Context operation. Otherwise token
    # expiry could masquerade as proof of immediate certification revocation.
    context_for(token, first)
    case(name="PPL-06-revocation-deny-same-bearer", expect="deny", cp_http_statuses=(403,), **allowed)
    context_for(token, first)
    case(name="PPL-07-replay-after-revocation-deny", expect="deny", cp_http_statuses=(403,), **allowed)
    context_for(token, first)
    verify(c, fixture, context_id, 3)
    c.sql("cpdb", "controlplane", "controlplane", f"""UPDATE capability.capability
                  SET status='DRAFT' WHERE capability_id='{fixture['capability']}'::uuid;""")
    check(scalar(c, "SELECT status FROM capability.capability WHERE code='payroll.run.read'") == "DRAFT",
          "DRAFT_CAPABILITY_NOT_RESTORED")
    check(scalar(c, f"""SELECT count(*) FROM capability.people_provider_choice
                         WHERE tenant_id='{fixture["tenant"]}'""") == "1",
          "CHOICE_HISTORY_MUTATED")
    receipt = {
        "schema": "people-dev-connected-witness.v1",
        "classification": "DISPOSABLE_SYNTHETIC_DEVELOPMENT",
        "cases": [r["case"] for r in results],
        "passed": len(results) == 7,
        "real_ory_hydra_signed_client_credentials": True,
        "real_cp_binary_and_https_erp_consumer": True,
        "independent_postgresql17_choice_and_resolution_readback": True,
        "same_bearer_context_replay_no_duplicate_choice": True,
        "same_tenant_wrong_legal_employer_denied_by_erp": True,
        "cross_tenant_context_denied": True,
        "missing_scope_denied": True,
        "revoked_certification_denied_with_unexpired_token": True,
        "canonical_people_capability_restored_to_draft": True,
        "statutory_za_ug_certification": False,
        "real_live_people_provider_qualified": False,
        "payroll_filing_or_money_movement": False,
        "protected_staging_production_authorized": False,
    }
    check(receipt["passed"], "INCOMPLETE_CASES")
    (args.out / "people-dev-witness.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
