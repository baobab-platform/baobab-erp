#!/usr/bin/env python3
"""DEV-09 second native iDempiere company/Organisation isolation probe.

Clones the native *catalogue rows* of a seeded synthetic reference AD_Client
and AD_Org with new native IDs, then maps to a separately registered CP tenant,
operating Organisation, legal entity and market. This is NOT the iDempiere
Initial Client Setup process or qualified second-company GL posting.
No attempt to infer financial authority from native IDs is permitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from erpalib import Compose

SECOND_CLIENT = 920001
SECOND_ORG = 920001
SECOND_PLACEMENT = "cc9f0b21-50f7-4878-8efb-7d30ed02e406"


def sqlsafe(value: str) -> str:
    """For runner-owned canonical fixture strings, never interpolate arbitrary SQL."""
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,100}", value):
        raise RuntimeError("DEV09_INVALID_FIXTURE_ID")
    return value


def place(compose: Compose, state: dict) -> None:
    second = state["second"]
    tenant = sqlsafe(second["tenant"])
    engine = sqlsafe(second["engine_instance"])
    legal = sqlsafe(second["legal_entity"])
    organisation = str(uuid.UUID(second["organisation"]))
    market = sqlsafe(second["market"])
    # The copy preserves actual native required columns and no foreign/unknown
    # names are treated as legal authority. The cloned application defaults do
    # not qualify the new company for iDempiere accounting transactions.
    statement = f"""
DO $plpgsql$
BEGIN
  IF EXISTS (SELECT 1 FROM adempiere.ad_client WHERE ad_client_id = {SECOND_CLIENT})
     OR EXISTS (SELECT 1 FROM adempiere.ad_org WHERE ad_org_id = {SECOND_ORG}) THEN
    RAISE EXCEPTION 'DEV09_SECOND_NATIVE_ID_ALREADY_ASSIGNED';
  END IF;
  INSERT INTO adempiere.ad_client
    SELECT (jsonb_populate_record(c, jsonb_build_object(
      'ad_client_id', {SECOND_CLIENT}, 'ad_client_uu', gen_random_uuid()::text,
      'name', 'DEV09 independent client B', 'value', 'DEV09B'))).*
      FROM adempiere.ad_client c WHERE c.ad_client_id = 11;
  IF NOT FOUND THEN RAISE EXCEPTION 'DEV09_PRIMARY_CLIENT_MISSING'; END IF;

  INSERT INTO adempiere.ad_org
    SELECT (jsonb_populate_record(o, jsonb_build_object(
      'ad_org_id', {SECOND_ORG}, 'ad_client_id', {SECOND_CLIENT},
      'ad_org_uu', gen_random_uuid()::text, 'name', 'DEV09 independent organisation B',
      'value', 'DEV09-ORG-B'))).*
      FROM adempiere.ad_org o WHERE o.ad_org_id = 11 AND o.ad_client_id = 11;
  IF NOT FOUND THEN RAISE EXCEPTION 'DEV09_PRIMARY_ORG_MISSING'; END IF;
END $plpgsql$;
INSERT INTO baobab_native.native_placement (placement_id, version, tenant_id,
  engine_instance_id, operating_organisation_id, legal_entity_id, market,
  ad_client_id, ad_org_id, effective_from, approved_by, checked_by,
  evidence_reference, erp_assignment_reference)
VALUES ('{SECOND_PLACEMENT}', 1, '{tenant}', '{engine}', '{organisation}',
        '{legal}', '{market}', {SECOND_CLIENT}, {SECOND_ORG}, now() - interval '1 hour',
        'Synthetic ERP Maker B', 'Synthetic ERP Checker B',
        'synthetic:dev09/independent-native-company', 'synthetic:dev09/erp-assignment-b');
"""
    compose.psql("erpdb", "postgres", "idempiere", statement)


def verified(compose: Compose, state: dict) -> dict:
    second = state["second"]
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
              second["market"], str(SECOND_CLIENT), str(SECOND_ORG)]
    if actual != [wanted]:
        raise RuntimeError("DEV09_SECOND_NATIVE_COMPANY_SCOPE_MISMATCH")
    # Verify the correct second row, and refusal of wrong-company resolution.
    isolated = compose.scalar("erpdb", "postgres", "idempiere", f"""
      SELECT baobab_native.current_placement({SECOND_CLIENT}, {SECOND_ORG}) IS NOT NULL
          AND baobab_native.current_placement(11, {SECOND_ORG}) IS NULL
          AND baobab_native.current_placement({SECOND_CLIENT}, 11) IS NULL
          AND (SELECT count(*) FROM baobab_native.native_placement
                WHERE ad_client_id IN (11, {SECOND_CLIENT}) AND effective_to IS NULL) = 2
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
              '{sqlsafe(state["legal_entity"])}', '{sqlsafe(state["market"])}', 11, {SECOND_ORG},
              now() - interval '1 hour', 'Synthetic Maker', 'Synthetic Checker',
              'synthetic:dev09/foreign-org-deny', 'synthetic:dev09/foreign-org-deny');
      COMMIT;
    """, check=False)
    if wrong_client.returncode == 0 or "BAOBAB_NATIVE_FINANCE_DENIED" not in wrong_client.stderr:
        raise RuntimeError("DEV09_FOREIGN_COMPANY_PLACEMENT_NOT_DENIED")
    # Native catalogue itself cannot reassign an org with an open placement.
    reassigned = compose.psql("erpdb", "postgres", "idempiere", f"""
      BEGIN;
      UPDATE adempiere.ad_org SET ad_client_id = 11 WHERE ad_org_id = {SECOND_ORG};
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
        "company_b_configured_via_idempiere_client_setup": False,
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
        place(cp, state)
    else:
        (args.out / "dev09-native-company.json").write_text(
            json.dumps(verified(cp, state), indent=2) + "\n")


if __name__ == "__main__":
    main()
