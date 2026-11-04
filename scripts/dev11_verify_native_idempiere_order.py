#!/usr/bin/env python3
"""Independent read-only native iDempiere order consequence verifier (DEV-11).

Reads real PostgreSQL 17 native adempiere C_Order and C_OrderLine in the same
read-only snapshot as ERP's inbox, execution, consequence, canonical outbox
and native placement. Never creates a native order or grants CP authority.
This separate native effect proof cannot alone qualify the entire L4-OPS-01.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

import psycopg

SOURCE = "urn:baobab-platform:service:baobab-trade"
EVENT_TYPE = "com.baobab-platform.trade.order.placed.v1"
CONSEQUENCE_EVENT = "com.baobab-platform.erp.order.consequence-changed.v1"
TENANT = re.compile(r"^tn_[a-z0-9]{3,60}$")
LEGAL = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
ORDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class NotProven(Exception):
    pass


def require(condition, code):
    if not condition:
        raise NotProven(code)


def unique(connection, sql, params, code):
    rows = connection.execute(sql, params).fetchall()
    require(len(rows) == 1, code)
    return rows[0]


def verify(connection, tenant, event_id, legal_entity, ad_client, ad_org, *, mapped_reference=False):
    require(TENANT.fullmatch(tenant) and LEGAL.fullmatch(legal_entity),
            "UNTRUSTED_OBSERVER_SCOPE")
    try:
        event_id = str(uuid.UUID(event_id))
    except ValueError:
        raise NotProven("INVALID_EVENT_ID") from None
    require(type(ad_client) is int and type(ad_org) is int
            and ad_client > 0 and ad_org > 0, "INVALID_NATIVE_COMPANY")

    inbox = unique(connection,
        """SELECT status, outcome_code, event_type, tenant_id, payload_json,
                  ce_idempotency_key
           FROM baobab.event_inbox
           WHERE envelope_format='cloudevents' AND ce_source=%s
             AND event_id=%s::uuid""", (SOURCE, event_id), "NATIVE_INBOX_NOT_UNIQUE")
    status, outcome, kind, stored_tenant, payload, idem = inbox
    require(status == "processed" and outcome in ("EXECUTED", "ADOPTED_NATIVE_ORDER")
            and kind == EVENT_TYPE and stored_tenant == tenant
            and isinstance(idem, str) and len(idem) >= 16
            and isinstance(payload, dict) and payload.get("legal_entity_id") == legal_entity,
            "NATIVE_INBOX_NOT_EXECUTED")
    order = payload.get("commerce_order_id")
    version = payload.get("order_version")
    lines = payload.get("lines")
    require(isinstance(order, str) and ORDER.fullmatch(order)
            and type(version) is int and version > 0
            and isinstance(lines, list) and 0 < len(lines) <= 500,
            "NATIVE_ORDER_PAYLOAD_INVALID")

    execution = unique(connection,
        """SELECT legal_entity_id, order_version, native_table, native_id,
                  source_event_id::text, erp_order_id, adopted
           FROM baobab.order_execution
           WHERE tenant_id=%s AND commerce_order_id=%s""",
        (tenant, order), "ERP_EXECUTION_NOT_UNIQUE")
    entity, stored_version, table, native_id, source_id, erp_id, adopted = execution
    require(entity == legal_entity and stored_version == version
            and table == "C_Order" and type(native_id) is int and native_id > 0
            and source_id == event_id and isinstance(erp_id, str)
            and erp_id.startswith("erp_")
            and adopted == (outcome == "ADOPTED_NATIVE_ORDER"),
            "NATIVE_EXECUTION_IDENTITY_MISMATCH")

    native_reference = order
    native_column = "poreference"
    if mapped_reference:
        binding = unique(connection,
            """SELECT native_uuid::text,native_id,desired_digest,first_source_event_id::text
               FROM baobab.order_native_reference
               WHERE tenant_id=%s AND legal_entity_id=%s AND commerce_order_id=%s
                 AND ad_client_id=%s AND ad_org_id=%s
                 AND order_version=%s AND creation_attempted_at IS NOT NULL""",
            (tenant,legal_entity,order,ad_client,ad_org,version), "NATIVE_REFERENCE_MAPPING_MISSING")
        expected_digest = "sha256:" + hashlib.sha256(json.dumps(payload,
            sort_keys=True,separators=(",",":"),allow_nan=False,
            ensure_ascii=False).encode("utf-8")).hexdigest()
        require(binding[1:] == (native_id,expected_digest,event_id),
                "NATIVE_REFERENCE_MAPPING_CHANGED")
        native_reference, native_column = binding[0], "c_order_uu"

    # The actual native JDBC-backed iDempiere C_Order must exist exactly once
    # across ALL companies, so a foreign client cannot satisfy the readback.
    actual_id, actual_client, actual_org, reference, docstatus = unique(
        connection,
        "SELECT c_order_id, ad_client_id, ad_org_id, " + native_column + ", docstatus "
        "FROM adempiere.c_order WHERE " + native_column + "=%s", (native_reference,),
        "IDEMPIERE_ORDER_MISSING_OR_DUPLICATED")
    require((actual_id, actual_client, actual_org, reference) ==
            (native_id, ad_client, ad_org, native_reference) and docstatus not in ("VO", "RE"),
            "IDEMPIERE_ORDER_FOREIGN_OR_VOID")

    line_count, distinct_lines, invalid_lines = connection.execute(
        """SELECT count(*), count(DISTINCT c_orderline_id),
                  count(*) FILTER (WHERE qtyordered <= 0)
           FROM adempiere.c_orderline
           WHERE c_order_id=%s AND ad_client_id=%s AND ad_org_id=%s""",
        (native_id, ad_client, ad_org)).fetchone()
    require(line_count == len(lines) and distinct_lines == line_count
            and invalid_lines == 0, "NATIVE_ORDER_LINES_INVALID")

    consequence = unique(connection,
        """SELECT legal_entity_id, order_version, erp_order_id, status,
                  revision, accounting_status
           FROM baobab.order_consequence
           WHERE tenant_id=%s AND commerce_order_id=%s""",
        (tenant, order), "ERP_CONSEQUENCE_MISSING")
    require(consequence[0:3] == (legal_entity, version, erp_id)
            and consequence[3] in ("accepted", "processing")
            and consequence[4] >= 1 and consequence[5] != "posted",
            "ERP_CONSEQUENCE_FALSE_FINANCIAL_STATUS")
    outbox_count = connection.execute(
        """SELECT count(*) FROM baobab.event_outbox
           WHERE envelope_format='cloudevents' AND event_type=%s
             AND tenant_id=%s AND ce_subject=%s""",
        (CONSEQUENCE_EVENT, tenant, "order:" + order)).fetchone()[0]
    require(outbox_count == 1, "CONSEQUENCE_EVENT_NOT_ATOMIC_OR_DUPLICATED")

    placement_count = connection.execute(
        """SELECT count(*) FROM baobab_native.native_placement
           WHERE tenant_id=%s AND legal_entity_id=%s
             AND ad_client_id=%s AND ad_org_id=%s
             AND effective_from<=now()
             AND (effective_to IS NULL OR effective_to>now())""",
        (tenant, legal_entity, ad_client, ad_org)).fetchone()[0]
    require(placement_count == 1, "NATIVE_PLACEMENT_NOT_UNIQUE_OR_ACTIVE")

    # The protected iDempiere JVM PEP writes its *own* CP-derived native
    # attribution in the same JDBC transaction. A matching native order row
    # inserted outside the JVM is insufficient. At least one C_OrderLine
    # must be bound to its exact C_Order source and approved company/placement.
    native_attributions = connection.execute(
        """SELECT count(*)
           FROM baobab_native.finance_authority_attribution a
           JOIN baobab_native.native_placement p
             ON p.placement_id=a.placement_id
            AND p.version=a.placement_version
           WHERE a.tenant_id=%s AND a.responsible_legal_entity_id=%s
             AND a.ad_client_id=%s AND a.ad_org_id=%s
             AND a.native_table IN ('C_Order', 'C_OrderLine')
             AND a.source_table='C_Order'
             AND a.source_record_id=%s
             AND a.operation_class='erp.sales-order.complete'
             AND a.decision_id IS NOT NULL AND a.cp_mandate_id IS NOT NULL
             AND a.context_id IS NOT NULL
             AND a.finance_baseline_version >= 1
             AND p.tenant_id=a.tenant_id
             AND p.operating_organisation_id=a.operating_organisation_id
             AND p.legal_entity_id=a.responsible_legal_entity_id""",
        (tenant, legal_entity, ad_client, ad_org, native_id)).fetchone()[0]
    require(native_attributions >= 1,
            "NATIVE_JVM_AUTHORITY_ATTRIBUTION_MISSING")

    return {
        "schema": "erp.dev11.independent-real-native-order.v1",
        "real_idempiere_order_readback": True,
        "native_reference_profile": "native-uuid-v1" if mapped_reference else "legacy-poreference",
        "lossless_native_reference_mapping_verified": bool(mapped_reference),
        "erp_inbox_proven_executed": True,
        "native_company_isolation": True,
        "native_order_line_count_verified": True,
        "erp_consequence_and_outbox_proven": True,
        "current_native_placement_proven": True,
        "native_jvm_authority_attribution_observed": True,
        "adopted_after_recovery": bool(adopted),
        "native_order_effect_qualified": True,
        "financial_posting_inferred": False,
        "iam_cp_live_authority_separately_required": True,
        "otel_exported_span_graph_separately_required": True,
        "l4_ops_01": "BLOCKED",
        "protected_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--legal-entity", required=True)
    parser.add_argument("--ad-client", type=int, required=True)
    parser.add_argument("--ad-org", type=int, required=True)
    parser.add_argument("--mapped-native-reference", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        with psycopg.connect(os.environ["ERP_DATABASE_URL"], autocommit=True) as db:
            db.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            receipt = verify(db, args.tenant, args.event_id,
                             args.legal_entity, args.ad_client, args.ad_org,
                             mapped_reference=args.mapped_native_reference)
            db.execute("COMMIT")
        success = True
    except (NotProven, psycopg.Error, OSError, KeyError, ValueError):
        receipt = {
            "schema": "erp.dev11.independent-real-native-order.v1",
            "native_order_effect_qualified": False,
            "reason": "NATIVE_READBACK_NOT_PROVEN",
            "l4_ops_01": "BLOCKED",
            "protected_acceptance": False,
        }
        success = False
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print("DEV11_REAL_NATIVE_ORDER=" + ("VERIFIED" if success else "BLOCKED"))
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
