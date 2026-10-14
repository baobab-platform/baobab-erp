-- P0-04B-05 ERP (ADR-ERP-022 amendment): directionality and derived costing at
-- the database COMMIT boundary, for placed AD_Clients only.
--
-- 1. Direction. Permission to record money received is never permission to
--    disburse it, and sales-side authority never covers purchases. A governed
--    payment is a receipt (IsReceipt='Y'); a governed invoice, order or
--    shipment is sales side (IsSOTrx='Y'); an allocation joins only those.
--    Completion and ledger posting must hold an attribution of the table's
--    OWN operation class, and the stored direction must still hold at COMMIT.
--    The direction of a governed document cannot be changed afterwards.
--    Bank statements and cash journals have no catalogued class and are not
--    completable or postable for a placed client.
-- 2. Derived costing. A native costing write may inherit authorization from a
--    catalogued root ERP operation only when ERP proves that it is a
--    deterministic consequence of that operation within the same database
--    transaction and under the same native placement, provenance and
--    legal-actor attribution. Costing writes without such provenance are
--    denied. Independent costing or revaluation operations require their own
--    catalogued authority.
--
-- Ids are NUMERIC(10) in iDempiere: every call site casts (N0004).

-- The catalogued operation class of a governed source table (ERP's own
-- table-to-operation policy, mirrored from NativeOperationResolver).
CREATE FUNCTION baobab_native.governed_class(p_table text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE lower(p_table)
    WHEN 'gl_journal' THEN 'erp.gl-journal.post'
    WHEN 'c_invoice' THEN 'erp.customer-invoice.issue'
    WHEN 'c_payment' THEN 'erp.payment.record'
    WHEN 'c_allocationhdr' THEN 'erp.allocation.record'
    WHEN 'm_inout' THEN 'erp.shipment.complete'
    WHEN 'c_order' THEN 'erp.sales-order.complete'
  END
$$;

-- True when the stored source row is in its governed direction.
CREATE FUNCTION baobab_native.direction_holds(p_table text, p_record integer)
RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE ok boolean;
BEGIN
  CASE lower(p_table)
    WHEN 'gl_journal' THEN ok := true;
    WHEN 'c_invoice' THEN SELECT issotrx = 'Y' INTO ok FROM adempiere.c_invoice WHERE c_invoice_id = p_record;
    WHEN 'c_order' THEN SELECT issotrx = 'Y' INTO ok FROM adempiere.c_order WHERE c_order_id = p_record;
    WHEN 'm_inout' THEN SELECT issotrx = 'Y' INTO ok FROM adempiere.m_inout WHERE m_inout_id = p_record;
    WHEN 'c_payment' THEN SELECT isreceipt = 'Y' INTO ok FROM adempiere.c_payment WHERE c_payment_id = p_record;
    WHEN 'c_allocationhdr' THEN
      SELECT NOT EXISTS (
        SELECT 1 FROM adempiere.c_allocationline al
          LEFT JOIN adempiere.c_invoice i ON i.c_invoice_id = al.c_invoice_id
          LEFT JOIN adempiere.c_payment p ON p.c_payment_id = al.c_payment_id
         WHERE al.c_allocationhdr_id = p_record
           AND ((COALESCE(al.c_invoice_id, 0) > 0 AND i.issotrx IS DISTINCT FROM 'Y')
             OR (COALESCE(al.c_payment_id, 0) > 0 AND p.isreceipt IS DISTINCT FROM 'Y'))) INTO ok;
    ELSE ok := false;
  END CASE;
  RETURN COALESCE(ok, false);
END $$;

-- True when THIS transaction holds a still-current attribution of the source
-- document's OWN operation class, and the source is in its governed direction.
CREATE FUNCTION baobab_native.has_governed_attribution(p_client integer, p_table text, p_record integer)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT baobab_native.governed_class(p_table) IS NOT NULL
     AND baobab_native.direction_holds(p_table, p_record)
     AND EXISTS (
       SELECT 1 FROM baobab_native.finance_authority_attribution a
        WHERE a.txid = txid_current() AND a.ad_client_id = p_client
          AND a.decision_id IS NOT NULL
          AND lower(a.source_table) = lower(p_table) AND a.source_record_id = p_record
          AND a.operation_class = baobab_native.governed_class(p_table)
          AND a.authority_expires_at > clock_timestamp())
$$;

CREATE OR REPLACE FUNCTION baobab_native.fact_acct_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_table text;
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  SELECT t.tablename INTO source_table FROM adempiere.ad_table t WHERE t.ad_table_id = NEW.ad_table_id;
  IF source_table IS NULL
     OR NOT baobab_native.has_governed_attribution(NEW.ad_client_id::integer, source_table,
                                                   NEW.record_id::integer) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: ledger posting without current authority at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION baobab_native.document_completion_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE record_id integer;
BEGIN
  -- A row inserted already completed is fenced exactly like a completion:
  -- direct SQL must not bypass the fence by skipping the draft state.
  IF NEW.docstatus NOT IN ('CO', 'CL')
     OR (TG_OP = 'UPDATE' AND OLD.docstatus IN ('CO', 'CL'))
     OR NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  record_id := (to_jsonb(NEW) ->> TG_ARGV[1])::numeric::integer;
  IF NOT baobab_native.has_governed_attribution(NEW.ad_client_id::integer, TG_ARGV[0], record_id) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: document completion without current authority at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

-- The governed direction of a document is fixed once it exists.
CREATE FUNCTION baobab_native.forbid_direction_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF baobab_native.client_is_placed(OLD.ad_client_id::integer)
     AND (to_jsonb(NEW) ->> TG_ARGV[0]) IS DISTINCT FROM (to_jsonb(OLD) ->> TG_ARGV[0]) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: a governed document cannot change direction'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE doc record;
BEGIN
  FOR doc IN SELECT * FROM (VALUES
      ('c_payment', 'isreceipt'), ('c_invoice', 'issotrx'), ('c_order', 'issotrx'), ('m_inout', 'issotrx'))
      AS t(relation, direction)
  LOOP
    EXECUTE format('CREATE TRIGGER baobab_direction_lock BEFORE UPDATE OF %I ON adempiere.%I
      FOR EACH ROW EXECUTE FUNCTION baobab_native.forbid_direction_change(%L)',
      doc.direction, doc.relation, doc.direction);
  END LOOP;
END $$;

-- Derived costing writes: each records, in the SAME transaction, the root
-- document and the CP decision it inherits. Append-only.
CREATE TABLE baobab_native.derived_write_attribution (
  derived_write_id bigserial PRIMARY KEY,
  txid bigint NOT NULL DEFAULT txid_current(),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  root_table text NOT NULL CHECK (root_table = 'M_InOut'),
  root_record_id integer NOT NULL CHECK (root_record_id > 0),
  decision_id uuid NOT NULL,
  derived_table text NOT NULL CHECK (derived_table = 'M_CostDetail'),
  ad_client_id integer NOT NULL CHECK (ad_client_id > 0),
  ad_org_id integer NOT NULL CHECK (ad_org_id >= 0),
  m_product_id integer NOT NULL CHECK (m_product_id > 0),
  c_acctschema_id integer NOT NULL CHECK (c_acctschema_id > 0),
  m_costelement_id integer NOT NULL CHECK (m_costelement_id >= 0)
);
CREATE INDEX derived_write_attribution_txid_idx
  ON baobab_native.derived_write_attribution (txid, ad_client_id, m_product_id, c_acctschema_id);

CREATE FUNCTION baobab_native.derived_write_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.txid := txid_current();
  NEW.recorded_at := clock_timestamp();
  -- The root must be authorised for its own class in this transaction, under
  -- the decision recorded here, in the same client; a sales shipment only.
  IF NOT baobab_native.has_governed_attribution(NEW.ad_client_id, NEW.root_table, NEW.root_record_id)
     OR NOT EXISTS (
       SELECT 1 FROM baobab_native.finance_authority_attribution a
        WHERE a.txid = NEW.txid AND a.ad_client_id = NEW.ad_client_id AND a.decision_id = NEW.decision_id
          AND lower(a.source_table) = lower(NEW.root_table) AND a.source_record_id = NEW.root_record_id)
     OR NOT EXISTS (
       SELECT 1 FROM adempiere.m_inout io
        WHERE io.m_inout_id = NEW.root_record_id AND io.ad_client_id = NEW.ad_client_id
          AND (NEW.ad_org_id = 0 OR io.ad_org_id = NEW.ad_org_id)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: costing write without an authorised root in this transaction'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER derived_write_insert_guard BEFORE INSERT ON baobab_native.derived_write_attribution
  FOR EACH ROW EXECUTE FUNCTION baobab_native.derived_write_insert_guard();

CREATE FUNCTION baobab_native.derived_write_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'derived write attribution is append-only' USING ERRCODE = '42501';
END $$;

CREATE TRIGGER derived_write_immutable BEFORE UPDATE OR DELETE ON baobab_native.derived_write_attribution
  FOR EACH ROW EXECUTE FUNCTION baobab_native.derived_write_immutable();

-- COMMIT fence on cost detail: it must be derived, in this transaction, from
-- the still-authorised sales shipment its own line belongs to.
CREATE FUNCTION baobab_native.cost_detail_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM baobab_native.derived_write_attribution d
         JOIN adempiere.m_inoutline l ON l.m_inout_id = d.root_record_id
        WHERE d.txid = txid_current() AND d.ad_client_id = NEW.ad_client_id::integer
          AND d.m_product_id = NEW.m_product_id::integer AND d.c_acctschema_id = NEW.c_acctschema_id::integer
          AND l.m_inoutline_id = NEW.m_inoutline_id
          AND baobab_native.has_governed_attribution(d.ad_client_id, d.root_table, d.root_record_id)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: cost detail without an authorised root at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER baobab_cost_detail_commit_fence AFTER INSERT OR UPDATE ON adempiere.m_costdetail
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION baobab_native.cost_detail_commit_fence();

-- COMMIT fence on aggregate cost: only a cost detail derived in this
-- transaction for the same client, product and schema (org or client level).
CREATE FUNCTION baobab_native.cost_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM baobab_native.derived_write_attribution d
        WHERE d.txid = txid_current() AND d.ad_client_id = NEW.ad_client_id::integer
          AND d.m_product_id = NEW.m_product_id::integer AND d.c_acctschema_id = NEW.c_acctschema_id::integer
          AND (d.ad_org_id = NEW.ad_org_id::integer OR NEW.ad_org_id = 0)
          AND baobab_native.has_governed_attribution(d.ad_client_id, d.root_table, d.root_record_id)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: cost update without an authorised root at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER baobab_cost_commit_fence AFTER INSERT OR UPDATE ON adempiere.m_cost
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION baobab_native.cost_commit_fence();
