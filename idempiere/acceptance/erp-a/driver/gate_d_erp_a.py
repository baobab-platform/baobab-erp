#!/usr/bin/env python3
"""EA v2.2 EA-R03 ERP-A engine-local harness driver (ADR-SHARED-037,
ADR-ERP-022 §4.3): seeds the REAL CP, places GardenWorld under it, then drives
the purchase-side scenarios through REAL iDempiere 13 and asserts persisted
state in BOTH databases (iDempiere's ledger and attribution, CP's immutable
decision history). Writes the evidence bundle and the receipt.

  gate_d_erp_a.py seed|place|scenarios --run DIR --out DIR --compose FILE

Engine-local real-component evidence on SYNTHETIC data: NOT EA Gate D, NOT L4.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erpalib import Compose, Erp, Evidence  # noqa: E402
from seed import CONTRACTING_ONLY, PURCHASE, ControlPlane  # noqa: E402

CLIENT = 11
DENIED = "BAOBAB_NATIVE_FINANCE_DENIED"
PLACEMENT = "5e0a7c3b-2d1f-4e6a-9b8c-7d6e5f4a3b21"
INGEST = "synthetic_evidence_ingest"
PO, MR, VI, VP, PA = ("erp.purchase-order.complete", "erp.material-receipt.complete", "erp.vendor-invoice.record",
                      "erp.vendor-payment.record", "erp.payables-allocation.record")
# iDempiere AD_Table ids.
T_ORDER, T_INOUT, T_INVOICE, T_PAYMENT, T_ALLOC, T_MATCHPO, T_MATCHINV = 259, 319, 318, 335, 735, 473, 472


def seed(args, compose: Compose, evidence: Evidence) -> None:
    cp = ControlPlane(compose, evidence)
    state = cp.seed()
    state.update(maker=cp.maker, checker=cp.checker, operator=cp.operator, mandate=cp.mandate)
    # Second CP tenant / legal entity / operating Organisation is genuinely
    # independent, but its registration and verified-legal rows are synthetic.
    cp_second = ControlPlane(compose, evidence, legal_entity="LE-ERPBUA", market="ZA",
                             currency="ZAR", market_key="za.gate.erpab")
    second = cp_second.seed()
    second.update(maker=cp_second.maker, checker=cp_second.checker,
                  operator=cp_second.operator, mandate=cp_second.mandate)
    state["second"] = second
    Path(args.run, "cp-seed.json").write_text(json.dumps(state))
    Path(args.out, "seed-notes.json").write_text(json.dumps(evidence.notes, indent=2))


def restore(args, compose: Compose, evidence: Evidence) -> tuple[ControlPlane, dict]:
    state = json.loads(Path(args.run, "cp-seed.json").read_text())
    cp = ControlPlane(compose, evidence)
    cp.maker, cp.checker, cp.operator = state["maker"], state["checker"], state["operator"]
    cp.tenant, cp.organisation, cp.engine_instance = state["tenant"], state["organisation"], state["engine_instance"]
    cp.mandate = state["mandate"]
    return cp, state


def place(args, compose: Compose, evidence: Evidence) -> None:
    """ERP-owned operator setup, as in the synthetic Gate D (run-gate-d.sh), but
    placing GardenWorld under the REAL CP tenant, Organisation, engine instance
    and market seeded above."""
    _, s = restore(args, compose, evidence)
    statement = f"""
-- Standard period control (ADR-ERP-008); Automatic Period Control would rewrite C_AcctSchema itself.
UPDATE adempiere.c_acctschema SET autoperiodcontrol = 'N' WHERE ad_client_id = 11;
-- Opening Average PO valuation at standard cost with the client-wide quantity on hand (operator setup).
INSERT INTO adempiere.m_cost
SELECT (jsonb_populate_record(c, jsonb_build_object(
          'c_acctschema_id', s.c_acctschema_id, 'm_cost_uu', gen_random_uuid()::text,
          'm_costelement_id', ae.m_costelement_id,
          'currentqty', q.qty, 'cumulatedqty', q.qty, 'cumulatedamt', q.qty * c.currentcostprice))).*
  FROM adempiere.m_cost c
  JOIN adempiere.m_costelement se ON se.m_costelement_id = c.m_costelement_id AND se.costingmethod = 'S'
   AND se.costelementtype = 'M'
  JOIN adempiere.m_costelement ae ON ae.ad_client_id = 11 AND ae.costingmethod = 'A' AND ae.isactive = 'Y'
  JOIN adempiere.c_acctschema s ON s.ad_client_id = 11
  JOIN (SELECT st.m_product_id, sum(st.qtyonhand) AS qty FROM adempiere.m_storageonhand st
         WHERE st.ad_client_id = 11 GROUP BY st.m_product_id) q ON q.m_product_id = c.m_product_id
 WHERE c.ad_client_id = 11 AND c.currentcostprice > 0 AND q.qty > 0
   AND c.c_acctschema_id = (SELECT c_acctschema1_id FROM adempiere.ad_clientinfo WHERE ad_client_id = 11)
   AND NOT EXISTS (SELECT 1 FROM adempiere.m_cost x WHERE x.c_acctschema_id = s.c_acctschema_id
     AND x.ad_client_id = 11 AND x.ad_org_id = c.ad_org_id AND x.m_product_id = c.m_product_id
     AND x.m_costtype_id = c.m_costtype_id AND x.m_costelement_id = ae.m_costelement_id
     AND x.m_attributesetinstance_id = c.m_attributesetinstance_id);
-- Open the current period for the purchase-side document types, and for the types whose native
-- refusal is asserted (vendor return MMS, AP credit memo APC), and allocations (CMA), so a refusal is
-- Baobab's, not a closed period.
UPDATE adempiere.c_periodcontrol pc SET periodstatus = 'O'
  FROM adempiere.c_period p
 WHERE p.c_period_id = pc.c_period_id AND p.ad_client_id = 11
   AND pc.docbasetype IN ('POO', 'MMR', 'MMS', 'API', 'APC', 'APP', 'CMA', 'MXP', 'MXI')
   AND current_date BETWEEN p.startdate AND p.enddate;
INSERT INTO baobab_native.native_placement (placement_id, version, tenant_id, engine_instance_id,
  operating_organisation_id, legal_entity_id, market, ad_client_id, ad_org_id, effective_from,
  approved_by, checked_by, evidence_reference, erp_assignment_reference)
VALUES ('{PLACEMENT}', 1, '{s["tenant"]}', '{s["engine_instance"]}',
  '{s["organisation"]}', '{s["legal_entity"]}', '{s["market"]}', 11, 11, now() - interval '1 day',
  'Synthetic Placement Maker', 'Synthetic Placement Checker', 'synthetic:erp-a/placement', 'synthetic:erp-a/plan/v1');
INSERT INTO baobab.financial_configuration_baseline (legal_entity_id, version, functional_currency,
  fiscal_year_start_month, chart_of_accounts_template, accounting_schema, tax_profile, costing_method,
  effective_from, approved_by, approved_at, evidence_reference)
VALUES ('{s["legal_entity"]}', 1, 'USD', 1, 'synthetic-gardenworld', 'synthetic-gardenworld', 'synthetic-gardenworld',
  'AVERAGE_PO', current_date - 30, 'Synthetic Finance Approver', now(), 'synthetic:erp-a/baseline');
-- ERP-B (N0008): the synthetic payment-execution evidence ingest login. Not a superuser, not iDempiere's role.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{INGEST}') THEN
    CREATE ROLE {INGEST} LOGIN NOSUPERUSER IN ROLE baobab_payment_evidence_ingest;
  END IF;
END $$;
"""
    compose.psql("erpdb", "postgres", "idempiere", statement)


class Scenarios:
    def __init__(self, args, compose: Compose, evidence: Evidence):
        self.args, self.c, self.ev = args, compose, evidence
        self.cp, self.state = restore(args, compose, evidence)
        self.erp = Erp(compose, args.run)
        self.n = 0

    # --- helpers -------------------------------------------------------------------------------
    def doc(self, kind: str, **props) -> dict:
        self.n += 1
        return self.erp.request(f"p{self.n:03d}-{kind}", action="pdoc", kind=kind, **props)

    def complete(self, table: str, record: str, **props) -> dict:
        self.n += 1
        return self.erp.request(f"c{self.n:03d}-{table}", action="completeDoc", table=table, id=record, **props)

    def repost(self, table: str, record: str, force: bool = False) -> dict:
        self.n += 1
        return self.erp.request(f"r{self.n:03d}-{table}", action="repostDoc", table=table, id=record,
                                force=str(force).lower())

    def q(self, statement: str) -> str:
        return self.erp.sql(statement)

    def attributed(self, table: str, record, cls: str) -> bool:
        return self.q(f"SELECT count(*) > 0 FROM baobab_native.finance_authority_attribution "
                      f"WHERE lower(source_table) = lower('{table}') AND source_record_id = {record} "
                      f"AND operation_class = '{cls}' AND decision_id IS NOT NULL") == "t"

    def cp_backed(self, table: str, record, cls: str) -> bool:
        """Every ERP attribution of this document names a decision that CP itself
        recorded as AUTHORIZED, for this class and this exact source document."""
        ids = [r for r in self.q(
            f"SELECT string_agg(DISTINCT decision_id::text, ',') FROM baobab_native.finance_authority_attribution "
            f"WHERE lower(source_table) = lower('{table}') AND source_record_id = {record} "
            f"AND operation_class = '{cls}'").split(",") if r]
        if not ids:
            return False
        quoted = ",".join(f"'{i}'" for i in ids)
        n = self.c.scalar("cpdb", "controlplane", "controlplane",
                          f"SELECT count(*) FROM registry.erp_posting_authority_decision WHERE decision_id IN ({quoted}) "
                          f"AND outcome = 'AUTHORIZED' AND operation_class = '{cls}' "
                          f"AND operation_reference LIKE 'erp/{cls}/{table}/{record}/%'")
        return n == str(len(ids))

    def cp_outcome(self, table: str, record, cls: str, outcome: str, negate: bool = False) -> bool:
        """CP recorded a decision with (or, negated, other than) this outcome for this source document."""
        op = "<>" if negate else "="
        return self.c.scalar("cpdb", "controlplane", "controlplane",
                             f"SELECT count(*) > 0 FROM registry.erp_posting_authority_decision "
                             f"WHERE outcome {op} '{outcome}' AND operation_class = '{cls}' "
                             f"AND operation_reference LIKE 'erp/{cls}/{table}/{record}/%'") == "t"

    def draft(self, rel: str, table_id: int, record) -> bool:
        """Still a draft: never completed, no ledger, no attribution of its completion."""
        return (bool(record) and self.q(f"SELECT docstatus FROM {rel} WHERE {rel}_id = {record}") == "DR"
                and self.facts(table_id, record) == "0")

    def balanced(self, table_id: int, record) -> bool:
        return self.q(f"SELECT count(*) > 0 AND sum(amtacctdr) = sum(amtacctcr) FROM fact_acct "
                      f"WHERE ad_table_id = {table_id} AND record_id = {record}") == "t"

    def status(self, rel: str, record) -> str:
        return self.q(f"SELECT docstatus || posted FROM {rel} WHERE {rel}_id = {record}")

    def facts(self, table_id: int, record) -> str:
        return self.q(f"SELECT count(*) FROM fact_acct WHERE ad_table_id = {table_id} AND record_id = {record}")

    def posted(self, rel: str, table: str, table_id: int, record, cls: str) -> bool:
        return (bool(record) and self.status(rel, record) == "COY" and self.balanced(table_id, record)
                and self.attributed(table, record, cls) and self.cp_backed(table, record, cls))

    def refused(self, rel: str, table_id: int, record, result: dict) -> bool:
        no_co = not record or self.q(f"SELECT count(*) FROM {rel} WHERE {rel}_id = {record} "
                                     f"AND docstatus IN ('CO','CL')") == "0"
        no_ledger = not record or self.facts(table_id, record) == "0"
        return no_co and no_ledger and DENIED in json.dumps(result)

    def fenced(self, sid: str, title: str, statement: str, tag: str) -> bool:
        out = self.erp.bypass(statement)
        Path(self.args.out, f"bypass-{sid}.txt").write_text(out + "\n")
        return self.ev.scenario(sid, title + ": refused at COMMIT",
                                tag in out.splitlines() and DENIED in out, out[-400:])

    def evidence(self, invoice, amount: str | None = None) -> bool:
        """ERP-B: SYNTHETIC_ENGINE_LOCAL payment-execution evidence for one vendor invoice, written by the
        synthetic ingest login, never by iDempiere. Proves the mechanism only, never a real disbursement."""
        rows = self.c.sql("erpdb", "adempiere", "idempiere",
                          f"SELECT i.c_bpartner_id, i.c_currency_id, c.iso_code, i.grandtotal, i.ad_org_id "
                          f"FROM adempiere.c_invoice i JOIN adempiere.c_currency c ON c.c_currency_id = i.c_currency_id "
                          f"WHERE i.c_invoice_id = {invoice or 0}")
        if not rows:
            return False
        partner, currency, iso, total, org = rows[-1]
        self.n += 1
        p = self.c.psql("erpdb", INGEST, "idempiere", f"""
INSERT INTO baobab_native.payment_execution_evidence (evidence_id, execution_authority, placement_id,
  placement_version, responsible_legal_entity_id, ad_client_id, ad_org_id, payee_reference, c_bpartner_id,
  obligation_reference, c_invoice_id, currency, c_currency_id, amount, executed_at, verified_at, verified_by,
  evidence_references)
VALUES (gen_random_uuid(), 'SYNTHETIC_ENGINE_LOCAL', '{PLACEMENT}', 1, '{self.state["legal_entity"]}', 11, {org},
  'erp:bpartner/{partner}', {partner}, 'erp:vendor-invoice/{invoice}', {invoice}, '{iso}', {currency},
  {amount or total}, now() - interval '2 minutes', now() - interval '1 minute', 'Synthetic Payment Verifier',
  ARRAY['synthetic:erp-b/payment-execution/{self.n}'])""", check=False)
        self.ev.note("synthetic-evidence", {"invoice": invoice, "amount": amount or total, "ok": p.returncode == 0,
                                            "stderr": p.stderr[-300:]})
        return p.returncode == 0

    def cost_rows(self, order_line_ids: str) -> str:
        return self.q(f"SELECT count(*) FROM m_costdetail WHERE c_orderline_id IN ({order_line_ids}) "
                      f"AND coalesce(m_inoutline_id, 0) = 0 AND coalesce(c_invoiceline_id, 0) = 0")

    # --- scenarios -----------------------------------------------------------------------------
    def run(self) -> None:
        ev = self.ev
        # S01-S06: the purchase-to-pay recording flow under a real CP mandate.
        r = self.doc("po", qty=3)
        po = r.get("id", "")
        ev.scenario("S01", "purchase order: CO, attributed to a CP-recorded AUTHORIZED decision",
                    bool(po) and self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {po or 0}") == "CO"
                    and self.attributed("C_Order", po, PO) and self.cp_backed("C_Order", po, PO), json.dumps(r))
        r = self.doc("receipt", order_id=po)
        rc = r.get("id", "")
        ev.scenario("S02", "material receipt: CO, posted, balanced Fact_Acct, CP-backed attribution",
                    self.posted("m_inout", "M_InOut", T_INOUT, rc, MR), json.dumps(r))
        lines = self.q(f"SELECT string_agg(c_orderline_id::text, ',') FROM c_orderline WHERE c_order_id = {po or 0}") or "0"
        # Under Average PO, iDempiere posts the receipt's M_MatchPO in the receipt's own posting: no
        # Fact_Acct (no purchase price variance), one order-line cost detail per accounting schema.
        mpo = self.q(f"SELECT min(mp.m_matchpo_id) FROM m_matchpo mp JOIN m_inoutline l ON l.m_inoutline_id = mp.m_inoutline_id "
                     f"WHERE l.m_inout_id = {rc or 0} AND mp.posted = 'Y'")
        derived = self.q(f"SELECT count(*) FROM baobab_native.derived_write_attribution "
                         f"WHERE root_table = 'M_InOut' AND root_record_id = {rc or 0}")
        ev.scenario("S03", "purchase costing: MatchPO posted, order-line cost detail derived from the authorised receipt",
                    bool(mpo) and int(self.cost_rows(lines)) > 0 and int(derived or 0) > 0,
                    f"matchpo={mpo} costs={self.cost_rows(lines)} derived={derived}")
        r = self.doc("vinvoice", order_id=po, receipt_id=rc)
        inv = r.get("id", "")
        mi = self.q(f"SELECT min(mi.m_matchinv_id) FROM m_matchinv mi JOIN c_invoiceline il "
                    f"ON il.c_invoiceline_id = mi.c_invoiceline_id WHERE il.c_invoice_id = {inv or 0}")
        ev.scenario("S04", "vendor invoice: CO, posted, balanced, CP-backed; matched to the receipt",
                    self.posted("c_invoice", "C_Invoice", T_INVOICE, inv, VI) and bool(mi), json.dumps(r))
        if mi and self.q(f"SELECT posted FROM m_matchinv WHERE m_matchinv_id = {mi}") != "Y":
            self.repost("M_MatchInv", mi)
        inv_costs = self.q(f"SELECT count(*) FROM m_costdetail cd JOIN c_invoiceline il ON il.c_invoiceline_id = cd.c_invoiceline_id "
                           f"WHERE il.c_invoice_id = {inv or 0} AND coalesce(cd.m_inoutline_id, 0) = 0")
        inv_derived = self.q(f"SELECT count(*) FROM baobab_native.derived_write_attribution "
                             f"WHERE root_table = 'C_Invoice' AND root_record_id = {inv or 0}")
        ev.scenario("S04b", "invoice match: MatchInv posted and balanced, invoice-line cost detail derived from the vendor invoice",
                    bool(mi) and self.q(f"SELECT posted FROM m_matchinv WHERE m_matchinv_id = {mi or 0}") == "Y"
                    and self.balanced(T_MATCHINV, mi or 0) and int(inv_costs or 0) > 0 and int(inv_derived or 0) > 0,
                    f"matchinv={mi} costs={inv_costs} derived={inv_derived}")
        self.evidence(inv)
        r = self.doc("vpayment", invoice_id=inv)
        pay = r.get("id", "")
        alloc = self.q(f"SELECT max(c_allocationhdr_id) FROM c_allocationline WHERE c_payment_id = {pay or 0}")
        ev.scenario("S05", "vendor payment RECORD: CO, posted, CP-backed; allocation under its own class; invoice paid",
                    self.posted("c_payment", "C_Payment", T_PAYMENT, pay, VP) and bool(alloc)
                    and self.q(f"SELECT docstatus FROM c_allocationhdr WHERE c_allocationhdr_id = {alloc or 0}") == "CO"
                    and self.attributed("C_AllocationHdr", alloc, PA)
                    and self.q(f"SELECT ispaid FROM c_invoice WHERE c_invoice_id = {inv or 0}") == "Y"
                    and self.q(f"SELECT isonline FROM c_payment WHERE c_payment_id = {pay or 0}") == "N",
                    json.dumps(r))
        r2 = self.doc("po", qty=1)
        po2 = r2.get("id", "")
        inv2 = self.doc("vinvoice", order_id=po2).get("id", "")
        self.evidence(inv2)
        pay2 = self.doc("vpayment", invoice_id=inv2, unallocated="true").get("id", "")
        r = self.doc("vallocation", invoice_id=inv2, payment_id=pay2)
        al = r.get("id", "")
        ev.scenario("S06", "manual payables allocation: CO, CP-backed attribution",
                    bool(al) and self.q(f"SELECT docstatus FROM c_allocationhdr WHERE c_allocationhdr_id = {al}") == "CO"
                    and self.cp_backed("C_AllocationHdr", al, PA), json.dumps(r))

        # S07: retry after commit and a forced background repost under authority: no duplicate ledger or costing.
        f0, c0 = self.facts(T_INOUT, rc or 0), self.cost_rows(lines)
        self.repost("M_InOut", rc)
        rf = self.repost("M_InOut", rc, force=True)
        ev.scenario("S07", "receipt retry and forced repost: ledger rebuilt balanced, costing not duplicated",
                    bool(rc) and self.facts(T_INOUT, rc) == f0 and self.balanced(T_INOUT, rc) and self.cost_rows(lines) == c0,
                    json.dumps(rf))

        # S08-S12: routes CP can never authorise (deny-by-name, ADR-SHARED-037 §3): refused natively.
        r = self.doc("vreturn", order_id=po)
        ev.scenario("S08", "vendor return (MMS, purchase side): refused", self.refused("m_inout", T_INOUT, r.get("id"), r),
                    json.dumps(r))
        r = self.doc("apcredit", order_id=po)
        ev.scenario("S09", "AP credit memo: refused", self.refused("c_invoice", T_INVOICE, r.get("id"), r), json.dumps(r))
        r = self.doc("payselection")
        ev.scenario("S10", "payment selection (native disbursement instruction): refused",
                    DENIED in json.dumps(r) and self.q("SELECT count(*) FROM c_payselection WHERE ad_client_id = 11 "
                                                       "AND name LIKE 'Baobab Gate D%'") == "0", json.dumps(r))
        r = self.doc("vpayment", invoice_id=inv2, online="true", unallocated="true")
        ev.scenario("S11", "online outbound payment (money movement): refused",
                    self.refused("c_payment", T_PAYMENT, r.get("id"), r)
                    and self.q("SELECT count(*) FROM c_payment WHERE ad_client_id = 11 AND isonline = 'Y' "
                               "AND description LIKE 'Baobab Gate D%'") == "0", json.dumps(r))
        ar = self.q("SELECT min(c_invoice_id) FROM c_invoice WHERE ad_client_id = 11 AND issotrx = 'Y' "
                    "AND docstatus = 'CO' AND ispaid = 'N'")
        self.evidence(inv2, amount="1.00")
        pay3 = self.doc("vpayment", amount="1.00").get("id", "")
        r = self.doc("vallocation", invoice_id=ar or 0, payment_id=pay3 or 0, amount="1.00")
        ev.scenario("S12", "mixed allocation (vendor payment against a customer invoice): refused",
                    bool(ar) and bool(pay3) and DENIED in json.dumps(r)
                    and self.q(f"SELECT count(*) FROM c_allocationline WHERE c_invoice_id = {ar or 0} "
                               f"AND c_payment_id = {pay3 or 0}") == "0", json.dumps(r))

        # S13-S17: direct SQL as iDempiere's own runtime role, bypassing the JVM: the COMMIT fence refuses.
        draft = self.doc("po", qty=1, complete="false").get("id", "")
        self.fenced("S13", "direct SQL purchase-order completion",
                    f"UPDATE adempiere.c_order SET docstatus = 'CO', processed = 'Y' WHERE c_order_id = {draft or 0}",
                    "UPDATE 1")
        self.fenced("S14", "direct SQL M_MatchPO insert",
                    f"""INSERT INTO adempiere.m_matchpo SELECT (jsonb_populate_record(mp, jsonb_build_object(
                          'm_matchpo_id', (SELECT max(m_matchpo_id) + 1 FROM adempiere.m_matchpo),
                          'm_matchpo_uu', gen_random_uuid()::text, 'posted', 'N'))).*
                          FROM adempiere.m_matchpo mp WHERE mp.m_matchpo_id = {mpo or 0}""", "INSERT 0 1")
        self.fenced("S15", "direct SQL receipt Fact_Acct insert",
                    f"""INSERT INTO adempiere.fact_acct SELECT (jsonb_populate_record(f, jsonb_build_object(
                          'fact_acct_id', (SELECT max(fact_acct_id) + 1 FROM adempiere.fact_acct),
                          'fact_acct_uu', gen_random_uuid()::text))).*
                          FROM adempiere.fact_acct f WHERE ad_table_id = {T_INOUT} AND record_id = {rc or 0} LIMIT 1""",
                    "INSERT 0 1")
        self.fenced("S16", "direct SQL order-line cost detail insert",
                    f"""INSERT INTO adempiere.m_costdetail SELECT (jsonb_populate_record(cd, jsonb_build_object(
                          'm_costdetail_id', (SELECT max(m_costdetail_id) + 1 FROM adempiere.m_costdetail),
                          'm_costdetail_uu', gen_random_uuid()::text))).*
                          FROM adempiere.m_costdetail cd WHERE cd.c_orderline_id IN ({lines})
                           AND coalesce(cd.m_inoutline_id, 0) = 0 LIMIT 1""", "INSERT 0 1")
        out = self.erp.bypass("INSERT INTO adempiere.c_payselection (ad_client_id, ad_org_id) VALUES (11, 11)")
        Path(self.args.out, "bypass-S17.txt").write_text(out + "\n")
        ev.scenario("S17", "direct SQL payment selection insert: refused", DENIED in out, out[-400:])
        out = self.erp.bypass(f"UPDATE adempiere.c_payment SET isonline = 'Y' WHERE c_payment_id = {pay or 0}")
        Path(self.args.out, "bypass-S18.txt").write_text(out + "\n")
        ev.scenario("S18", "direct SQL: a recorded vendor payment cannot become online",
                    bool(pay) and DENIED in out
                    and self.q(f"SELECT isonline FROM c_payment WHERE c_payment_id = {pay or 0}") == "N", out[-400:])

        # S19: crash window. Completion is authorised and attributed in the transaction, then iDempiere is
        # SIGKILLed before COMMIT: nothing persists in ERP; CP keeps the decision it recorded.
        crash = self.doc("po", qty=1, complete="false").get("id", "")
        rows = (f"SELECT count(*) FROM baobab_native.finance_authority_attribution "
                f"WHERE lower(source_table) = 'c_order' AND source_record_id = {crash or 0}")
        before = self.q(rows)
        self.n += 1
        name = f"c{self.n:03d}-crash"
        held_props = dict(action="completeDoc", table="C_Order", id=crash, holdSeconds="120", hold_marker="crash")
        requests = self.erp.dir / "requests"
        (requests / f"{name}.tmp").write_text("".join(f"{k}={v}\n" for k, v in held_props.items()))
        (requests / f"{name}.tmp").rename(requests / f"{name}.properties")
        marker = self.erp.held("crash")
        self.c.run("kill", "-s", "SIGKILL", "erp")
        time.sleep(3)
        ev.scenario("S19", "crash between authority and COMMIT: no completion, no attribution; CP decision retained",
                    bool(crash) and marker == "attributed=1"
                    and self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {crash or 0}") == "DR"
                    and self.q(rows) == before
                    and self.c.scalar("cpdb", "controlplane", "controlplane",
                                      "SELECT count(*) > 0 FROM registry.erp_posting_authority_decision "
                                      f"WHERE outcome = 'AUTHORIZED' AND operation_reference LIKE "
                                      f"'erp/{PO}/C_Order/{crash}/C_Order/{crash}/document:%'") == "t",
                    f"marker={marker!r} attributions before={before} after={self.q(rows)}")
        self.restart_erp()
        r = self.complete("C_Order", crash)
        ev.scenario("S20", "after restart the same completion re-decides and commits once",
                    self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {crash or 0}") == "CO"
                    and self.cp_backed("C_Order", crash, PO), json.dumps(r))

        # S21: the 30-second lease outlived inside the transaction: the COMMIT fence refuses.
        lease = self.doc("po", qty=1, complete="false").get("id", "")
        r = self.complete("C_Order", lease, holdSeconds="35", hold_marker="lease")
        ev.scenario("S21", "lease expiry before COMMIT: refused by the fence, order stays DR",
                    bool(lease) and self.erp.held("lease", 5) == "attributed=1"
                    and self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {lease or 0}") == "DR"
                    and r.get("committed") != "true", json.dumps(r))

        # S22-S24: real CP authority changes. Revoked mandate; a narrower mandate; CP unavailable.
        d_rev = self.doc("po", qty=1, complete="false").get("id", "")
        d_inv_po = self.doc("po", qty=1).get("id", "")
        d_inv = self.doc("vinvoice", order_id=d_inv_po, complete="false").get("id", "")
        self.cp.revoke(self.cp.mandate)
        r = self.complete("C_Order", d_rev)
        ev.scenario("S22", "mandate revoked through CP: completion refused, CP records the non-authorization",
                    self.draft("c_order", T_ORDER, d_rev) and r.get("committed") != "true" or
                    self.draft("c_order", T_ORDER, d_rev) and r.get("complete_ok") == "false",
                    json.dumps(r))
        ev.scenario("S22b", "CP decision history holds the refusal for that exact order",
                    self.cp_outcome("C_Order", d_rev, PO, "AUTHORIZED", negate=True), "")
        self.cp.mandate = self.cp.propose(CONTRACTING_ONLY, "erp-a/mandate-contracting-only")
        r_inv = self.complete("C_Invoice", d_inv)
        r_po = self.complete("C_Order", d_rev)
        ev.scenario("S23", "contracting-only mandate: vendor invoice refused, purchase order authorised",
                    self.q(f"SELECT docstatus FROM c_invoice WHERE c_invoice_id = {d_inv or 0}") == "DR"
                    and self.q(f"SELECT count(*) FROM fact_acct WHERE ad_table_id = {T_INVOICE} AND record_id = {d_inv or 0}") == "0"
                    and self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {d_rev or 0}") == "CO"
                    and self.cp_backed("C_Order", d_rev, PO),
                    json.dumps({"invoice": r_inv, "order": r_po}))
        self.cp.revoke(self.cp.mandate)
        self.cp.mandate = self.cp.propose(PURCHASE, "erp-a/mandate-purchase-renewed")
        d_down = self.doc("po", qty=1, complete="false").get("id", "")
        down_rows = (f"SELECT count(*) FROM baobab_native.finance_authority_attribution "
                     f"WHERE lower(source_table) = 'c_order' AND source_record_id = {d_down or 0}")
        down_before = self.q(down_rows)
        self.c.run("stop", "cp")
        r = self.complete("C_Order", d_down)
        self.c.run("start", "cp")
        ev.scenario("S24", "CP unavailable: fail closed, order stays DR without ledger or attribution",
                    bool(d_down) and self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {d_down}") == "DR"
                    and self.q(down_rows) == down_before and self.facts(T_ORDER, d_down) == "0"
                    and r.get("complete_ok") != "true", json.dumps(r))
        self.wait_cp()
        r = self.complete("C_Order", d_down)
        ev.scenario("S25", "CP back with a renewed mandate: the same order completes under a new decision",
                    self.q(f"SELECT docstatus FROM c_order WHERE c_order_id = {d_down}") == "CO"
                    and self.cp_backed("C_Order", d_down, PO), json.dumps(r))

        self.erp_b()

        self.ev.scenario("S26", "no ERP attribution without a CP-recorded AUTHORIZED decision (whole run)",
                         self.orphans() == 0, f"orphans={self.orphans()}")

    def bound(self, payment) -> bool:
        return bool(payment) and self.q(f"SELECT count(*) FROM baobab_native.payment_execution_binding "
                                        f"WHERE c_payment_id = {payment}") == "1"

    def erp_b(self) -> None:
        """ERP-B (ADR-SHARED-038): vendor-payment recording needs bound, still-matching execution evidence;
        a payment is allocated only to its evidence obligation; uncatalogued families are denied by name."""
        ev = self.ev
        vendor_paid = lambda: self.q("SELECT count(*) FROM c_payment WHERE ad_client_id = 11 AND isreceipt = 'N' "
                                     "AND description LIKE 'Baobab Gate D%'")
        po_b = self.doc("po", qty=1).get("id", "")
        inv_b = self.doc("vinvoice", order_id=po_b).get("id", "")
        before = vendor_paid()
        r = self.doc("vpayment", invoice_id=inv_b)
        ev.scenario("B01", "vendor payment without execution evidence: refused at creation, no payment row",
                    bool(inv_b) and self.refused("c_payment", T_PAYMENT, r.get("id"), r) and vendor_paid() == before,
                    json.dumps(r))
        total = self.q(f"SELECT grandtotal FROM c_invoice WHERE c_invoice_id = {inv_b or 0}")
        short = self.q(f"SELECT grandtotal - 0.01 FROM c_invoice WHERE c_invoice_id = {inv_b or 0}")
        ingested = self.evidence(inv_b, amount=short)
        r = self.doc("vpayment", invoice_id=inv_b)
        ev.scenario("B02", "evidence for another amount: refused",
                    ingested and self.refused("c_payment", T_PAYMENT, r.get("id"), r) and vendor_paid() == before,
                    json.dumps(r))
        ingested = self.evidence(inv_b)
        r = self.doc("vpayment", invoice_id=inv_b)
        pay_b = r.get("id", "")
        ev.scenario("B03", "matching evidence: payment RECORDED, bound, posted and CP-backed; the invoice is paid",
                    ingested and self.posted("c_payment", "C_Payment", T_PAYMENT, pay_b, VP) and self.bound(pay_b)
                    and self.q(f"SELECT ispaid FROM c_invoice WHERE c_invoice_id = {inv_b or 0}") == "Y",
                    json.dumps(r))
        before = vendor_paid()
        r = self.doc("vpayment", invoice_id=inv_b, unallocated="true", amount=total)
        ev.scenario("B04", "evidence already bound to a payment: a second payment is refused",
                    bool(pay_b) and self.refused("c_payment", T_PAYMENT, r.get("id"), r) and vendor_paid() == before,
                    json.dumps(r))
        po_c, po_d = self.doc("po", qty=1).get("id", ""), self.doc("po", qty=1).get("id", "")
        inv_c = self.doc("vinvoice", order_id=po_c).get("id", "")
        inv_d = self.doc("vinvoice", order_id=po_d).get("id", "")
        self.evidence(inv_c)
        pay_c = self.doc("vpayment", invoice_id=inv_c, unallocated="true").get("id", "")
        r = self.doc("vallocation", invoice_id=inv_d, payment_id=pay_c or 0)
        ev.scenario("B05", "allocating a vendor payment to another invoice than its evidence obligation: refused",
                    self.bound(pay_c) and bool(inv_d) and DENIED in json.dumps(r)
                    and self.q(f"SELECT count(*) FROM c_allocationline WHERE c_payment_id = {pay_c or 0}") == "0",
                    json.dumps(r))
        r = self.doc("vallocation", invoice_id=inv_c, payment_id=pay_c or 0)
        al = r.get("id", "")
        ev.scenario("B06", "allocating it to its evidence obligation: CO, CP-backed",
                    bool(al) and self.q(f"SELECT docstatus FROM c_allocationhdr WHERE c_allocationhdr_id = {al}") == "CO"
                    and self.cp_backed("C_AllocationHdr", al, PA), json.dumps(r))
        out = self.erp.bypass(f"""INSERT INTO baobab_native.payment_execution_evidence (evidence_id,
            execution_authority, placement_id, placement_version, responsible_legal_entity_id, ad_client_id, ad_org_id,
            payee_reference, c_bpartner_id, obligation_reference, c_invoice_id, currency, c_currency_id, amount,
            executed_at, verified_at, verified_by, evidence_references)
          SELECT gen_random_uuid(), 'SYNTHETIC_ENGINE_LOCAL', '{PLACEMENT}', 1, '{self.state["legal_entity"]}', 11, 11,
            'erp:bpartner/x', i.c_bpartner_id, 'erp:vendor-invoice/x', i.c_invoice_id, c.iso_code, i.c_currency_id,
            i.grandtotal, now(), now(), 'Forged Verifier', ARRAY['forged']
          FROM adempiere.c_invoice i JOIN adempiere.c_currency c ON c.c_currency_id = i.c_currency_id
          WHERE i.c_invoice_id = {inv_d or 0}""")
        Path(self.args.out, "bypass-B07.txt").write_text(out + "\n")
        ev.scenario("B07", "iDempiere's runtime role writing execution evidence by direct SQL: refused",
                    (DENIED in out and "ingest role" in out or "permission denied" in out)
                    and self.q(f"SELECT count(*) FROM baobab_native.payment_execution_evidence "
                               f"WHERE c_invoice_id = {inv_d or 0}") == "0", out[-400:])
        # Denied by name through the native models (the JVM veto) ...
        for sid, kind, rel in (("B08", "bankstatement", "c_bankstatement"), ("B09", "cash", "c_cash"),
                               ("B10", "inventory", "m_inventory")):
            n0 = self.q(f"SELECT count(*) FROM {rel} WHERE ad_client_id = 11")
            r = self.doc(kind, complete="false")
            ev.scenario(sid, f"{kind} through the native model: refused by name, nothing persists",
                        DENIED in json.dumps(r) and self.q(f"SELECT count(*) FROM {rel} WHERE ad_client_id = 11") == n0,
                        json.dumps(r))
        # ... and by direct SQL as the runtime role (PostgreSQL alone).
        refused, outs = [], []
        for rel in ("c_bankstatement", "c_bankstatementline", "c_cash", "c_cashline", "m_inventory", "m_inventoryline",
                    "m_movement", "m_movementline", "m_production", "m_productionline", "m_productionplan",
                    "c_landedcost", "c_landedcostallocation"):
            out = self.erp.bypass(f"INSERT INTO adempiere.{rel} (ad_client_id, ad_org_id) VALUES (11, 11)")
            outs.append(f"--- {rel}\n{out}")
            if DENIED in out:
                refused.append(rel)
        Path(self.args.out, "bypass-B11.txt").write_text("\n".join(outs) + "\n")
        ev.scenario("B11", "direct SQL into every denied-by-name family: refused by PostgreSQL",
                    len(refused) == 13, f"refused={refused}")
        is_super = self.c.scalar("erpdb", "postgres", "idempiere",
                                 "SELECT rolsuper FROM pg_roles WHERE rolname = 'adempiere'")
        ev.note("runtime-role", {"adempiere_is_superuser": is_super,
                                 "meaning": "a superuser can disable triggers; production must run iDempiere as a "
                                            "non-superuser role that is not a member of baobab_payment_evidence_ingest"})

    def orphans(self) -> int:
        ids = [r[0] for r in self.c.sql("erpdb", "adempiere", "idempiere",
                                        "SELECT DISTINCT decision_id FROM baobab_native.finance_authority_attribution "
                                        "WHERE decision_id IS NOT NULL")]
        if not ids:
            return 0
        quoted = ",".join(f"'{i}'" for i in ids)
        found = int(self.c.scalar("cpdb", "controlplane", "controlplane",
                                  f"SELECT count(*) FROM registry.erp_posting_authority_decision "
                                  f"WHERE outcome = 'AUTHORIZED' AND decision_id IN ({quoted})"))
        return len(ids) - found

    def restart_erp(self) -> None:
        ready = self.erp.dir / "ready"
        ready.unlink(missing_ok=True)
        self.c.run("start", "erp")
        deadline = time.time() + 600
        while time.time() < deadline and not ready.exists():
            time.sleep(3)
        if not ready.exists():
            raise RuntimeError("iDempiere did not restart")
        # Pending requests from before the kill must not replay.
        for stale in (self.erp.dir / "requests").glob("*"):
            stale.unlink()

    def wait_cp(self) -> None:
        from erpalib import CP, call
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if call("GET", CP + "/healthz", timeout=3).status == 200:
                    return
            except OSError:
                pass  # restarting: retried until the deadline
            time.sleep(1)
        raise RuntimeError("CP did not come back")


def receipt(args, evidence: Evidence) -> None:
    """The v2.2 receipt fields (EA v2.2 §7): candidate and dependency SHAs, Shared
    pins, image digests, executing profile, real vs simulated components, scenario
    ids with PASS/FAIL and the evidence location."""
    def digest(image: str) -> str:
        p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True)
        return p.stdout.strip() or "unavailable"

    repo = Path(__file__).resolve().parents[4]
    lock = (repo / "contracts.lock.yaml")
    shared_pin = ""
    if lock.exists():
        for line in lock.read_text().splitlines():
            if line.strip().startswith("commit:"):
                shared_pin = line.split(":", 1)[1].strip().strip('"')
                break
    report = {
        "receipt": "EA-R03 ERP-A and ERP-B engine-local real-component harness",
        "classification": "ENGINE-LOCAL real-component evidence on SYNTHETIC data. NOT EA Gate D. NOT L4 "
                          "(L4 runs only on the Infrastructure INT-01 runner). Protected routes stay fail-closed; "
                          "nothing here activates staging or production.",
        "candidate": {"repository": "baobab-platform/baobab-erp", "sha": os.environ.get("ERP_COMMIT", "")},
        "dependencies": {"baobab-cp": os.environ.get("CP_COMMIT", "")},
        "shared_pins": {"contracts.lock.yaml": shared_pin,
                        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else ""},
        "images": {"erp": {"ref": os.environ.get("ERP_IMAGE", ""), "id": digest(os.environ.get("ERP_IMAGE", ""))},
                   "cp": {"ref": os.environ.get("CP_IMAGE", ""), "id": digest(os.environ.get("CP_IMAGE", ""))},
                   "issuer": {"ref": os.environ.get("PYTHON_IMAGE", ""), "id": digest(os.environ.get("PYTHON_IMAGE", ""))}},
        "executing_profile": "engine-local integration (BAOBAB_ENVIRONMENT=integration; iDempiere acceptance runtime)",
        "components": {
            "real": ["iDempiere 13 with the shipped Baobab finance veto", "Baobab native migrations and COMMIT fences",
                     "CP release binary and its migrations", "PostgreSQL 17 (ERP and CP)", "genuine Hydra OAuth workload and Kratos native identity records", "TLS edge (nginx)"],
            "simulated": ["CP administrative fixtures: test OIDC issuer with real RS256 JWTs; genuine Hydra workload and Kratos readback do NOT prove human admin authorisation",
                          "recorded synthetic CP rows: legal-entity verification, market assignment, "
                          + "engine instance binding, human identities",
                          "GardenWorld synthetic business data",
                          "payment-execution evidence: SYNTHETIC_ENGINE_LOCAL, written by a synthetic ingest login; "
                          + "proves the provenance mechanism only, never a real disbursement (ADR-SHARED-038)"],
            "provider": "none: no money movement; vendor payment is RECORDING only (ADR-SHARED-037, ADR-SHARED-038)"},
        "notes": evidence.notes,
        "scenarios": evidence.scenarios,
        "result": "PASS" if evidence.failures() == 0 else "FAIL",
        "evidence_location": os.environ.get("EVIDENCE_LOCATION", str(Path(args.out).resolve())),
    }
    Path(args.out, "erp-a-receipt.json").write_text(json.dumps(report, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["seed", "place", "scenarios"])
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--compose", required=True)
    args = parser.parse_args()
    compose, evidence = Compose(args.compose), Evidence(args.out)
    if args.step == "seed":
        seed(args, compose, evidence)
    elif args.step == "place":
        place(args, compose, evidence)
    else:
        try:
            Scenarios(args, compose, evidence).run()
        except Exception as broken:  # an aborted run is a failed run, with its cause in the report
            evidence.scenario("S00", "harness completed every scenario", False, repr(broken)[:400])
        receipt(args, evidence)
        with open(Path(args.out, "erp-a-report.txt"), "a") as f:
            f.write(f"ERP-A failures: {evidence.failures()}\n")


if __name__ == "__main__":
    main()
