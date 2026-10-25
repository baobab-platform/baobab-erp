#!/usr/bin/env python3
"""DEV-09 iDempiere 13 native InitialClientSetup for independent company B.

Requires a running *real* iDempiere JVM and its unmodified native process,
configured accounting schema, plus a distinct CP-governed tenant, operating
Organisation, legal entity and market. Records never represent production
registration or grants and no second-company GL posting is claimed here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import uuid

from erpalib import Compose, Erp

SECOND_PLACEMENT = "cc9f0b21-50f7-4878-8efb-7d30ed02e406"
EXPECTED_NAME = "DEV09 Independent Company B"
EXPECTED_ORG = "DEV09-ORG-B"


def sqlsafe(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,100}", value):
        raise RuntimeError("DEV09_INVALID_FIXTURE_ID")
    return value


def observed_company(compose: Compose, client: int, org: int) -> None:
    rows = compose.sql("erpdb", "postgres", "idempiere", f"""
      SELECT c.name, o.value, c.ad_client_id, o.ad_org_id,
             EXISTS (SELECT 1 FROM adempiere.ad_clientinfo ci
                      WHERE ci.ad_client_id = c.ad_client_id
                        AND ci.c_acctschema1_id > 0)
        FROM adempiere.ad_client c
        JOIN adempiere.ad_org o ON o.ad_client_id=c.ad_client_id
       WHERE c.ad_client_id={client} AND o.ad_org_id={org}
         AND o.isactive='Y'
    """)
    if rows != [[EXPECTED_NAME, EXPECTED_ORG, str(client), str(org), "t"]]:
        raise RuntimeError("DEV09_NATIVE_CLIENT_SETUP_NOT_VERIFIED")


def place(compose: Compose, state: dict, run: Path) -> None:
    second = state["second"]
    # Actual iDempiere InitialClientSetup Process 53161 must create all
    # accounting and security material; direct AD_Client INSERT is forbidden.
    result = Erp(compose, str(run)).request(
        "dev09-company-b-setup", timeout=540,
        action="initClient", profile="DEV09_SECOND_COMPANY_ONLY")
    if result.get("native_setup_process") != "53161" or result.get("accounting_schema_present") != "true":
        raise RuntimeError("DEV09_NATIVE_CLIENT_SETUP_PROCESS_FAILED")
    try:
        client, org = int(result["client"]), int(result["org"])
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError("DEV09_NATIVE_CLIENT_SETUP_INVALID_IDS") from e
    if client <= 11 or org <= 11:
        raise RuntimeError("DEV09_NATIVE_CLIENT_SETUP_INVALID_IDS")
    observed_company(compose, client, org)
    tenant = sqlsafe(second["tenant"])
    engine = sqlsafe(second["engine_instance"])
    legal = sqlsafe(second["legal_entity"])
    organisation = str(uuid.UUID(second["organisation"]))
    market = sqlsafe(second["market"])
    compose.psql("erpdb", "postgres", "idempiere", f"""
    INSERT INTO baobab_native.native_placement (placement_id, version, tenant_id,
      engine_instance_id, operating_organisation_id, legal_entity_id, market,
      ad_client_id, ad_org_id, effective_from, approved_by, checked_by,
      evidence_reference, erp_assignment_reference)
    VALUES ('{SECOND_PLACEMENT}', 1, '{tenant}', '{engine}', '{organisation}',
            '{legal}', '{market}', {client}, {org}, now() - interval '1 hour',
            'Synthetic ERP Maker B', 'Synthetic ERP Checker B',
            'synthetic:dev09/independent-native-company',
            'synthetic:dev09/erp-assignment-b');
    """)
    # Finance readiness is ERP-owned and does not grant CP legal authority.
    # The private synthetic acceptance baseline must follow native setup;
    # only the second company's accounting schema is selected.
    compose.psql("erpdb", "postgres", "idempiere", f"""
    INSERT INTO baobab.financial_configuration_baseline (
      legal_entity_id, version, functional_currency, fiscal_year_start_month,
      chart_of_accounts_template, accounting_schema, tax_profile, costing_method,
      effective_from, approved_by, approved_at, evidence_reference)
    VALUES ('{legal}', 1, 'ZAR', 1, 'synthetic-default-coa',
            'idempiere-initial-client-setup-53161', 'synthetic-za',
            'AVERAGE_PO', current_date - 30, 'Synthetic Finance Approver B',
            now(), 'synthetic:dev09/finance-baseline-b');
    UPDATE adempiere.c_periodcontrol pc SET periodstatus='O'
      FROM adempiere.c_period p
      WHERE p.c_period_id=pc.c_period_id AND p.ad_client_id={client}
        AND pc.docbasetype='GLJ'
        AND current_date BETWEEN p.startdate AND p.enddate;
    """)
    # Private ephemeral state, not published in the sanitised evidence report.
    (run / "native-company.json").write_text(json.dumps({"client": client, "org": org}) + "\n")


def verified(compose: Compose, state: dict, run: Path) -> dict:
    second = state["second"]
    native = json.loads((run / "native-company.json").read_text())
    client, org = native["client"], native["org"]
    observed_company(compose, client, org)
    actual = compose.sql("erpdb", "postgres", "idempiere", f"""
      SELECT p.tenant_id, p.operating_organisation_id::text, p.legal_entity_id,
             btrim(p.market), p.ad_client_id, p.ad_org_id
        FROM baobab_native.native_placement p
        JOIN adempiere.ad_client c ON c.ad_client_id = p.ad_client_id
        JOIN adempiere.ad_org o ON o.ad_org_id = p.ad_org_id
              AND o.ad_client_id = c.ad_client_id AND o.isactive = 'Y'
       WHERE p.placement_id = '{SECOND_PLACEMENT}' AND p.effective_to IS NULL
    """)
    wanted = [second["tenant"], second["organisation"], second["legal_entity"],
              second["market"], str(client), str(org)]
    if actual != [wanted]:
        raise RuntimeError("DEV09_SECOND_NATIVE_COMPANY_SCOPE_MISMATCH")

    isolated = compose.scalar("erpdb", "postgres", "idempiere", f"""
      SELECT
        (SELECT count(*) FROM baobab_native.native_placement p
          JOIN adempiere.ad_org o ON o.ad_org_id=p.ad_org_id
                                AND o.ad_client_id=p.ad_client_id
          WHERE p.ad_client_id={client} AND p.ad_org_id={org}
            AND p.effective_to IS NULL AND o.isactive='Y') = 1
        AND (SELECT count(*) FROM baobab_native.native_placement
          WHERE (ad_client_id=11 AND ad_org_id={org})
             OR (ad_client_id={client} AND ad_org_id=11)) = 0
        AND (SELECT count(*) FROM baobab_native.native_placement
          WHERE ad_client_id IN (11, {client}) AND effective_to IS NULL) = 2
    """) == "t"
    if not isolated:
        raise RuntimeError("DEV09_SECOND_NATIVE_MAPPING_NOT_ISOLATED")

    wrong_client = compose.psql("erpdb", "postgres", "idempiere", f"""
      BEGIN;
      INSERT INTO baobab_native.native_placement
        (placement_id, version, tenant_id, engine_instance_id, operating_organisation_id,
         legal_entity_id, market, ad_client_id, ad_org_id, effective_from,
         approved_by, checked_by, evidence_reference, erp_assignment_reference)
      VALUES (gen_random_uuid(), 1, '{sqlsafe(state["tenant"])}',
              '{sqlsafe(state["engine_instance"])}', '{state["organisation"]}',
              '{sqlsafe(state["legal_entity"])}', '{sqlsafe(state["market"])}', 11, {org},
              now() - interval '1 hour', 'Synthetic Maker', 'Synthetic Checker',
              'synthetic:dev09/foreign-org-deny', 'synthetic:dev09/foreign-org-deny');
      COMMIT;
    """, check=False)
    if wrong_client.returncode == 0 or "BAOBAB_NATIVE_FINANCE_DENIED" not in wrong_client.stderr:
        raise RuntimeError("DEV09_FOREIGN_COMPANY_PLACEMENT_NOT_DENIED")

    reassigned = compose.psql("erpdb", "postgres", "idempiere", f"""
      BEGIN;
      UPDATE adempiere.ad_org SET ad_client_id = 11 WHERE ad_org_id = {org};
      COMMIT;
    """, check=False)
    if reassigned.returncode == 0 or "BAOBAB_NATIVE_FINANCE_DENIED" not in reassigned.stderr:
        raise RuntimeError("DEV09_NATIVE_ORG_REASSIGNMENT_NOT_DENIED")

    return {
        "schema": "dev09-independent-native-company.v1",
        "native_company_and_org_rows_observed": True,
        "distinct_cp_tenant_organisation_legal_entity_market": True,
        "native_current_placement_isolated": True,
        "wrong_native_client_placement_denied": True,
        "native_org_reassignment_denied": True,
        "company_b_configured_via_idempiere_client_setup": True,
        "second_company_accounting_schema_observed": True,
        "second_company_native_jvm_posting_qualified": False,
        "protected_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["place", "verify"])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compose", required=True)
    args = parser.parse_args()
    state = json.loads((args.run / "cp-seed.json").read_text())
    if state["tenant"] == state["second"]["tenant"] or state["organisation"] == state["second"]["organisation"]:
        raise RuntimeError("DEV09_SECOND_CP_TENANT_OR_ORG_NOT_INDEPENDENT")
    cp = Compose(args.compose)
    if args.phase == "place":
        place(cp, state, args.run)
    else:
        (args.out / "dev09-native-company.json").write_text(
            json.dumps(verified(cp, state, args.run), indent=2) + "\n")


if __name__ == "__main__":
    main()
