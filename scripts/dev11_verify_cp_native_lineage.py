#!/usr/bin/env python3
"""Independent DEV-11 CP -> protected iDempiere financial authority lineage.

Reads TWO separate, real PostgreSQL databases with independent READ ONLY
connections. CP immutable AUTHORIZED decisions must match JVM-inserted native
finance attribution for the exact sales-order line/source transaction. It does
not trust a producer assertion, a CP HTTP response echoed by ERP, or a fake
iDempiere REST server. Does not grant or execute native operations.

The verifier may pass only the historical *authority lineage* component.
Runtime JVM sentinel, broker receipts, business effect, source provenance and
OTLP exports are distinct mandatory L4 gates and never inferred here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

import psycopg
from psycopg.rows import dict_row

SALE = "erp.sales-order.complete"
ACTIVITY = "SALES_ORDER_COMMITMENT"
ROLE = "CONTRACTING_PARTY"


class EvidenceMissing(Exception):
    pass


def require(value, reason):
    if not value:
        raise EvidenceMissing(reason)


def uuid_text(value):
    try:
        parsed = str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return ""
    return parsed


def query_native(db, tenant, order, client, org):
    record = db.execute(
        """SELECT c_order_id, ad_client_id, ad_org_id, poreference, issotrx,
                  docstatus
             FROM adempiere.c_order
            WHERE poreference=%s""", (order,)).fetchall()
    require(len(record) == 1, "NATIVE_SALES_ORDER_NOT_UNIQUE")
    native = record[0]
    require(native["ad_client_id"] == client and native["ad_org_id"] == org
            and native["issotrx"] == "Y" and native["docstatus"] not in ("VO", "RE"),
            "NATIVE_SALES_ORDER_COMPANY_INVALID")
    native_id = native["c_order_id"]

    audits = db.execute(
        """SELECT decision_id::text, context_id::text, cp_mandate_id::text,
                  placement_id::text, placement_version,
                  tenant_id, operating_organisation_id::text,
                  responsible_legal_entity_id, operation_class, source_table,
                  source_record_id, ad_client_id, ad_org_id,
                  finance_baseline_version, received_at, authority_expires_at,
                  evidence_reference
             FROM baobab_native.finance_authority_attribution
            WHERE tenant_id=%s AND ad_client_id=%s AND ad_org_id=%s
              AND lower(source_table)=lower('C_Order')
              AND source_record_id=%s
              AND operation_class=%s
              AND decision_id IS NOT NULL AND cp_mandate_id IS NOT NULL
            ORDER BY recorded_at""",
        (tenant, client, org, native_id, SALE)).fetchall()
    require(len(audits) >= 1 and len(audits) <= 100,
            "NATIVE_JVM_CP_ATTRIBUTION_MISSING")
    require(any(a["source_table"].lower() == "c_order" for a in audits),
            "NATIVE_SOURCE_DOCUMENT_INVALID")
    return native_id, audits


def cp_decision(cp, audit, *, tenant, entity, market, native_id):
    did = uuid_text(audit["decision_id"])
    require(did and uuid_text(audit["context_id"]) and
            uuid_text(audit["cp_mandate_id"]) and
            uuid_text(audit["placement_id"]), "NATIVE_AUDIT_UUID_INVALID")
    rows = cp.execute(
        """SELECT decision_id::text, context_id::text,
                  placement_id::text, placement_version,
                  engine_instance_id, operation_class, operation_reference,
                  outcome, tenant_id, operating_organisation_id::text, market,
                  legal_actor_role, activity, mandate_id::text,
                  responsible_legal_entity_id, evaluated_at, expires_at,
                  evidence_references
             FROM registry.erp_posting_authority_decision
            WHERE decision_id=%s::uuid""", (did,)).fetchall()
    require(len(rows) == 1, "CP_IMMUTABLE_DECISION_NOT_FOUND")
    d = rows[0]
    require(d["outcome"] == "AUTHORIZED" and
            d["context_id"] == audit["context_id"] and
            d["placement_id"] == audit["placement_id"] and
            d["placement_version"] == audit["placement_version"] and
            d["operation_class"] == SALE and
            d["tenant_id"] == tenant and
            d["operating_organisation_id"] == audit["operating_organisation_id"] and
            d["market"] == market and d["legal_actor_role"] == ROLE and
            d["activity"] == ACTIVITY and
            d["mandate_id"] == audit["cp_mandate_id"] and
            d["responsible_legal_entity_id"] == entity and
            isinstance(d["engine_instance_id"], str) and
            d["engine_instance_id"].startswith("ei_") and
            d["operation_reference"].startswith(
                "erp/" + SALE + "/C_Order/" + str(native_id) + "/") and
            d["evaluated_at"] <= audit["received_at"] < d["expires_at"] and
            audit["authority_expires_at"] <= d["expires_at"] and
            len(d["evidence_references"] or []) >= 1,
            "CP_NATIVE_AUTHORITY_JOIN_DENIED")

    ctx = cp.execute(
        """SELECT tenant_id, authority_purpose, resolved_at, expires_at
             FROM context.resolved_context WHERE context_id=%s::uuid""",
        (d["context_id"],)).fetchall()
    require(len(ctx) == 1 and ctx[0]["tenant_id"] == tenant
            and ctx[0]["authority_purpose"] == "RUNTIME"
            and ctx[0]["resolved_at"] <= d["evaluated_at"]
            and (ctx[0]["expires_at"] is None or
                 d["evaluated_at"] < ctx[0]["expires_at"]),
            "CP_RUNTIME_CONTEXT_PROVENANCE_DENIED")

    mandate = cp.execute(
        """SELECT tenant_id, operating_organisation_id::text,
                  responsible_legal_entity_id, roles, activity_scope, market_scope,
                  effective_from, approved_by::text, created_by::text,
                  approved_at, legal_actor_verification_reference
             FROM registry.operating_legal_actor_mandate
            WHERE mandate_id=%s::uuid""",
        (d["mandate_id"],)).fetchall()
    require(len(mandate) == 1 and
            mandate[0]["tenant_id"] == tenant and
            mandate[0]["operating_organisation_id"] == d["operating_organisation_id"] and
            mandate[0]["responsible_legal_entity_id"] == entity and
            ROLE in mandate[0]["roles"] and
            ACTIVITY in mandate[0]["activity_scope"] and
            market in mandate[0]["market_scope"] and
            mandate[0]["effective_from"] <= d["evaluated_at"] and
            mandate[0]["approved_by"] and mandate[0]["created_by"] and
            mandate[0]["approved_by"] != mandate[0]["created_by"] and
            mandate[0]["approved_at"] is not None and
            mandate[0]["approved_at"] <= d["evaluated_at"] and
            mandate[0]["legal_actor_verification_reference"],
            "CP_MANDATE_HISTORY_NOT_INDEPENDENTLY_APPROVED")
    return d


def verify(erp, cp, *, tenant, order, entity, market, client, org):
    require(market in ("ZA", "UG", "US") and client > 0 and org > 0
            and tenant.startswith("tn_") and entity.startswith("LE-")
            and order.startswith("order_"),
            "OBSERVER_SCOPE_INVALID")
    native_id, audits = query_native(erp, tenant, order, client, org)
    decisions = []
    for a in audits:
        require(a["responsible_legal_entity_id"] == entity and
                a["finance_baseline_version"] >= 1 and
                a["received_at"] < a["authority_expires_at"],
                "NATIVE_BASELINE_OR_AUTHORITY_WINDOW_INVALID")
        decisions.append(cp_decision(
            cp, a, tenant=tenant, entity=entity, market=market,
            native_id=native_id))

    # Source order may contain header and line attributes; each JVM authority
    # used is present as a real, immutable CP decision, never an ERP echo.
    require(len(decisions) == len(audits), "CP_DECISION_COVERAGE_INCOMPLETE")
    return {
        "schema": "baobab.erp.dev11.independent-cp-jvm-lineage.v1",
        "source": "TWO_INDEPENDENT_POSTGRES_READ_ONLY_OBSERVERS",
        "immutable_cp_decisions_match_jvm_native_attributions": True,
        "all_jvm_order_decisions_cp_authorized": True,
        "runtime_context_provenance_current_at_decision": True,
        "independent_maker_checker_mandate_history": True,
        "observed_native_attribution_rows": len(audits),
        "native_cp_lineage_qualified": True,
        "real_erp_order_effect_separate_gate": True,
        "native_jvm_protected_sentinel_separate_gate": True,
        "broker_and_otel_separate_gates": True,
        "l4_ops_01": "BLOCKED",
        "protected_acceptance": False,
    }


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--tenant", required=True)
    args.add_argument("--commerce-order", required=True)
    args.add_argument("--legal-entity", required=True)
    args.add_argument("--market", required=True)
    args.add_argument("--ad-client", required=True, type=int)
    args.add_argument("--ad-org", required=True, type=int)
    args.add_argument("--output", required=True)
    v = args.parse_args()
    try:
        with psycopg.connect(os.environ["ERP_NATIVE_DATABASE_URL"], row_factory=dict_row) as erp:
            with psycopg.connect(os.environ["CP_DATABASE_URL"], row_factory=dict_row) as cp:
                erp.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cp.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                report = verify(
                    erp, cp, tenant=v.tenant, order=v.commerce_order,
                    entity=v.legal_entity, market=v.market,
                    client=v.ad_client, org=v.ad_org)
        passed = True
    except (EvidenceMissing, psycopg.Error, KeyError, ValueError, TypeError):
        passed = False
        report = {
            "schema": "baobab.erp.dev11.independent-cp-jvm-lineage.v1",
            "native_cp_lineage_qualified": False,
            "reason": "INDEPENDENT_CP_JVM_LINEAGE_NOT_PROVEN",
            "l4_ops_01": "BLOCKED",
            "protected_acceptance": False,
        }
    out = Path(v.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("DEV11_NATIVE_CP_IMMUTABLE_LINEAGE=" + ("PASS" if passed else "BLOCKED"))
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
