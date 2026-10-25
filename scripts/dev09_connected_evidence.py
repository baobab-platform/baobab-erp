#!/usr/bin/env python3
"""Closed DEV-09 real-Ory + second native-company component observations.

This deliberately does not upgrade the original 40 PASS / 8 BLOCKED ERP-A
receipt or claim Kratos-backed CP human authority. Native company setup and
its own JVM GL posting must both be independently observed before reporting.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED = {
    "dev09-ory-provision.json": {
        "schema": "dev09-ory-provision.v1",
        "hydra_native_client_readback": True,
        "hydra_client_credentials_only": True,
        "kratos_distinct_human_records": True,
        "cp_admin_authority_from_kratos": False,
        "protected_qualified": False,
    },
    "dev09-ory-consumption.json": {
        "schema": "dev09-ory-consumption.v1",
        "real_hydra_issued": True,
        "cp_current_tenant_org_context": True,
        "wrong_org_denied": True,
        "second_tenant_org_context": True,
        "mixed_tenant_org_denied": True,
        "wrong_audience_denied": True,
        "missing_context_scope_denied": True,
        "legal_actor_decision_tested_by_native_erp": True,
        "independent_provider_qualified": False,
        "protected_qualified": False,
    },
    "dev09-native-company.json": {
        "schema": "dev09-independent-native-company.v1",
        "native_company_and_org_rows_observed": True,
        "distinct_cp_tenant_organisation_legal_entity_market": True,
        "native_current_placement_isolated": True,
        "wrong_native_client_placement_denied": True,
        "native_org_reassignment_denied": True,
        "company_b_configured_via_idempiere_client_setup": True,
        "second_company_accounting_schema_observed": True,
        "second_company_native_jvm_posting_qualified": True,
        "second_company_cp_decision_and_balanced_fact_acct": True,
        "protected_qualified": False,
    },
}


def read_one(root: Path, filename: str, expected: dict) -> dict:
    path = root / filename
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError("DEV09_REFERENCE_EVIDENCE_MISSING_OR_UNSAFE")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("DEV09_REFERENCE_DUPLICATE_FIELD")
            obj[key] = value
        return obj
    observed = json.loads(path.read_bytes(), object_pairs_hook=unique)
    if not isinstance(observed, dict) or not expected.items() <= observed.items():
        raise ValueError("DEV09_REFERENCE_EVIDENCE_MISMATCH")
    if any(type(observed[key]) is not type(value) for key, value in expected.items()):
        raise ValueError("DEV09_REFERENCE_EVIDENCE_TYPE")
    return observed


def build(root: Path, erp_sha: str, cp_sha: str, iam_sha: str) -> dict:
    if not all(SHA.fullmatch(x) for x in (erp_sha, cp_sha, iam_sha)):
        raise ValueError("DEV09_REFERENCE_SOURCE_PIN_REQUIRED")
    source = {name: read_one(root, name, expected) for name, expected in REQUIRED.items()}
    if source["dev09-ory-provision.json"].get("iam_source_sha") != iam_sha:
        raise ValueError("DEV09_REFERENCE_IAM_SOURCE_MISMATCH")
    # Both independent issuer/provisioning and native role-bound evidence exist.
    # Neither proves protected identity onboarding or joined cross-engine accounting.
    return {
        "schema": "dev09-erp-connected-components.v1",
        "erp_source_sha": erp_sha, "cp_source_sha": cp_sha, "iam_source_sha": iam_sha,
        "evidence_class": "REAL_ORY_CP_NATIVE_PG_COMPONENT_SYNTHETIC_LEGAL_CONTEXT",
        "environment": "ISOLATED_INTEGRATION",
        "result": "BLOCKED",
        "cases": [
            {"id": "hydra-client-credentials-cp-current", "result": "PASS"},
            {"id": "distinct-native-company-org-ownership", "result": "PASS"},
            {"id": "mixed-tenant-org-denial", "result": "PASS"},
            {"id": "kratos-backed-human-cp-authority", "result": "BLOCKED",
             "reason": "CP_ADMINISTRATIVE_TOKENS_SYNTHETIC"},
            {"id": "second-native-company-jvm-accounting", "result": "PASS",
             "reason": "INDEPENDENT_PROTECTED_AND_JOINED_CROSS_ENGINE_ACCOUNTING_STILL_UNPROVEN"},
            {"id": "independent-legal-provider", "result": "BLOCKED",
             "reason": "SYNTHETIC_REGISTER_AND_MANDATE_ROWS"},
            {"id": "subscriptions-payments-gl-settlement", "result": "BLOCKED",
             "reason": "NO_JOINED_OWNER_PROVIDER_ACCEPTANCE"},
        ],
        "production_authorized": False, "protected_acceptance": False,
        "money_moved": False, "full_dev09_qualified": False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--directory", required=True, type=Path)
    ap.add_argument("--erp-sha", required=True)
    ap.add_argument("--cp-sha", required=True)
    ap.add_argument("--iam-sha", required=True)
    a = ap.parse_args()
    out, digest = (a.directory / "dev09-connected-report.json",
                   a.directory / "dev09-connected-report.sha256.json")
    out.unlink(missing_ok=True)
    digest.unlink(missing_ok=True)
    raw = (json.dumps(build(a.directory, a.erp_sha, a.cp_sha, a.iam_sha),
                      indent=2) + "\n").encode()
    out.write_bytes(raw)
    digest.write_text(json.dumps({"file": out.name, "sha256": hashlib.sha256(raw).hexdigest()},
                                  indent=2) + "\n")


if __name__ == "__main__":
    main()
