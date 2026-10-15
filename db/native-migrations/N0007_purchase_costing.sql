-- P0-04B ERP increment ERP-A (ADR-ERP-022 §4.2/§4.3): purchase costing as a
-- derived write, as observed on real iDempiere 13 (Gate D, GardenWorld,
-- Average PO costing). Posting an M_MatchPO writes, per accounting schema, one
-- M_CostDetail whose ONLY source is the purchase-order line (C_OrderLine_ID,
-- IsSOTrx='N', the line's org) and then updates the client-level M_Cost
-- buckets, all in the posting transaction.
--
-- Such a cost detail inherits authorization from exactly one material receipt
-- that holds current authority of its own class in THIS transaction and is
-- matched to that order line by an M_MatchPO of the same client; its org is the
-- receipt's org or 0. Zero or several candidate receipts deny.
--
-- Posting an M_MatchInv (the vendor invoice matched to the receipt) writes, per
-- accounting schema, one M_CostDetail whose ONLY source is the vendor-invoice
-- line (C_InvoiceLine_ID, IsSOTrx='N'), then updates M_Cost, alongside the
-- match's own balanced ledger. ADR-ERP-022 §4.3 already places an M_MatchInv
-- under its vendor invoice; that invoice is this cost detail's root, but only
-- while the line is matched in the same client and the invoice is of class
-- erp.vendor-invoice.record (never an AP credit memo or a sales invoice).
--
-- Every other costing origin stays denied (landed cost, inventory, movement,
-- production, revaluation: ERP-B or later).
--
-- Ids are NUMERIC(10) in iDempiere: every call site casts (N0004).

-- The one authorised material receipt a purchase-order-line cost detail derives from, or NULL.
CREATE FUNCTION baobab_native.purchase_cost_root(p_client integer, p_org integer, p_order_line integer)
RETURNS integer LANGUAGE sql STABLE AS $$
  WITH candidates AS (
    SELECT DISTINCT io.m_inout_id::integer AS receipt
      FROM adempiere.m_matchpo mp
      JOIN adempiere.m_inoutline l ON l.m_inoutline_id = mp.m_inoutline_id AND l.ad_client_id = mp.ad_client_id
      JOIN adempiere.m_inout io ON io.m_inout_id = l.m_inout_id AND io.ad_client_id = mp.ad_client_id
     WHERE mp.c_orderline_id = p_order_line AND mp.ad_client_id = p_client
       AND (p_org = 0 OR io.ad_org_id = p_org)
       AND baobab_native.has_current_attribution_for(p_client, 'M_InOut', io.m_inout_id::integer,
                                                     'erp.material-receipt.complete'))
  SELECT CASE WHEN count(*) = 1 THEN min(receipt) END FROM candidates
$$;

-- The vendor invoice a vendor-invoice-line cost detail derives from, or NULL.
-- Deterministic (the line's own invoice), so it does not depend on authority:
-- the JVM decides that root and the COMMIT fence requires its attribution.
CREATE FUNCTION baobab_native.invoice_cost_root(p_client integer, p_org integer, p_invoice_line integer)
RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT i.c_invoice_id::integer
    FROM adempiere.c_invoiceline il
    JOIN adempiere.c_invoice i ON i.c_invoice_id = il.c_invoice_id AND i.ad_client_id = il.ad_client_id
   WHERE il.c_invoiceline_id = p_invoice_line AND il.ad_client_id = p_client
     AND (p_org = 0 OR i.ad_org_id = p_org)
     AND baobab_native.governed_class_of('C_Invoice', i.c_invoice_id::integer) = 'erp.vendor-invoice.record'
     AND EXISTS (SELECT 1 FROM adempiere.m_matchinv mi
                  WHERE mi.c_invoiceline_id = il.c_invoiceline_id AND mi.ad_client_id = p_client)
$$;

-- COMMIT fence on cost detail (redefines N0005): a cost detail must be derived,
-- in this transaction, from the still-authorised root that caused it: the sales
-- shipment its own line belongs to, the material receipt matched to its
-- purchase-order line, or the vendor invoice its matched invoice line belongs to.
CREATE OR REPLACE FUNCTION baobab_native.cost_detail_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r adempiere.m_costdetail%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
  IF NOT baobab_native.client_is_placed(r.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM baobab_native.derived_write_attribution d
        WHERE d.txid = txid_current() AND d.ad_client_id = r.ad_client_id::integer
          AND d.m_product_id = r.m_product_id::integer AND d.c_acctschema_id = r.c_acctschema_id::integer
          AND baobab_native.has_governed_attribution(d.ad_client_id, d.root_table, d.root_record_id)
          AND (
            -- sales shipment: the detail's own line belongs to the root shipment
            (d.root_table = 'M_InOut'
             AND EXISTS (SELECT 1 FROM adempiere.m_inoutline l
                          WHERE l.m_inout_id = d.root_record_id AND l.m_inoutline_id = r.m_inoutline_id))
            -- purchase: an order-line-only detail derived from the one matched, authorised receipt
            OR (d.root_table = 'M_InOut'
                AND COALESCE(r.m_inoutline_id, 0) = 0 AND COALESCE(r.c_orderline_id, 0) > 0
                AND COALESCE(r.c_invoiceline_id, 0) = 0 AND COALESCE(r.m_matchinv_id, 0) = 0
                AND COALESCE(r.m_inventoryline_id, 0) = 0 AND COALESCE(r.m_movementline_id, 0) = 0
                AND COALESCE(r.m_productionline_id, 0) = 0 AND COALESCE(r.c_projectissue_id, 0) = 0
                AND COALESCE(r.pp_cost_collector_id, 0) = 0
                AND baobab_native.purchase_cost_root(r.ad_client_id::integer, r.ad_org_id::integer,
                                                     r.c_orderline_id::integer) = d.root_record_id)
            -- invoice match: an invoice-line-only detail derived from its own matched vendor invoice
            OR (d.root_table = 'C_Invoice' AND r.issotrx = 'N'
                AND COALESCE(r.m_inoutline_id, 0) = 0 AND COALESCE(r.c_orderline_id, 0) = 0
                AND COALESCE(r.c_invoiceline_id, 0) > 0 AND COALESCE(r.m_matchinv_id, 0) = 0
                AND COALESCE(r.m_inventoryline_id, 0) = 0 AND COALESCE(r.m_movementline_id, 0) = 0
                AND COALESCE(r.m_productionline_id, 0) = 0 AND COALESCE(r.c_projectissue_id, 0) = 0
                AND COALESCE(r.pp_cost_collector_id, 0) = 0
                AND baobab_native.invoice_cost_root(r.ad_client_id::integer, r.ad_org_id::integer,
                                                    r.c_invoiceline_id::integer) = d.root_record_id))) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: cost detail without an authorised root at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

-- Derived-write guard (redefines N0005): the root must be authorised for its own
-- class in this transaction, under the decision recorded here, in the same
-- client and org: a shipment or material receipt (M_InOut) or, for
-- invoice-match costing, a vendor invoice (C_Invoice). No other root exists.
CREATE OR REPLACE FUNCTION baobab_native.derived_write_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.txid := txid_current();
  NEW.recorded_at := clock_timestamp();
  IF NOT baobab_native.has_governed_attribution(NEW.ad_client_id, NEW.root_table, NEW.root_record_id)
     OR NOT EXISTS (
       SELECT 1 FROM baobab_native.finance_authority_attribution a
        WHERE a.txid = NEW.txid AND a.ad_client_id = NEW.ad_client_id AND a.decision_id = NEW.decision_id
          AND lower(a.source_table) = lower(NEW.root_table) AND a.source_record_id = NEW.root_record_id)
     OR NOT (
       (NEW.root_table = 'M_InOut' AND EXISTS (
          SELECT 1 FROM adempiere.m_inout io
           WHERE io.m_inout_id = NEW.root_record_id AND io.ad_client_id = NEW.ad_client_id
             AND (NEW.ad_org_id = 0 OR io.ad_org_id = NEW.ad_org_id)))
       OR (NEW.root_table = 'C_Invoice' AND EXISTS (
          SELECT 1 FROM adempiere.c_invoice i
           WHERE i.c_invoice_id = NEW.root_record_id AND i.ad_client_id = NEW.ad_client_id
             AND (NEW.ad_org_id = 0 OR i.ad_org_id = NEW.ad_org_id)
             AND baobab_native.governed_class_of('C_Invoice', NEW.root_record_id) = 'erp.vendor-invoice.record'))) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: costing write without an authorised root in this transaction'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

ALTER TABLE baobab_native.derived_write_attribution
  DROP CONSTRAINT derived_write_attribution_root_table_check,
  ADD CONSTRAINT derived_write_attribution_root_table_check CHECK (root_table IN ('M_InOut', 'C_Invoice'));
