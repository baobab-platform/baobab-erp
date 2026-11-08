-- ERP native ADR-008/016/017/022: durable protection of accounting and
-- completed-source history. Forward-only; do NOT edit the applied N0001-N0009.
--
-- N0003/0005/0006 already fence Fact_Acct INSERT at COMMIT, and native
-- BEFORE-model/document hooks enforce live CP posting authority. Neither
-- mechanism by itself prevents direct SQL UPDATE/DELETE of posted ledger rows,
-- a completed header's accounting identity, or its original charge lines.
-- A reversal is a *new*, governed accounting fact, never a mutation of a
-- historical Fact_Acct row. There is currently no catalogued native reversal
-- operation for a placed client: fail CLOSED instead of granting one here.
--
-- Scope is historical placement, not merely an ACTIVE lease. Closing a
-- placement must not make its old financial history writable.
-- This migration does not supply a financial posting engine or a new CP grant.

CREATE FUNCTION baobab_native.forbid_placed_ledger_rewrite()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF baobab_native.client_is_placed(OLD.ad_client_id::integer)
     OR (TG_OP = 'UPDATE' AND baobab_native.client_is_placed(NEW.ad_client_id::integer)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: immutable posted ledger; use an authorised reversal'
      USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

-- The existing INSERT COMMIT fence remains unchanged and mandatory.
CREATE TRIGGER baobab_ledger_immutable_history
  BEFORE UPDATE OR DELETE ON adempiere.fact_acct
  FOR EACH ROW EXECUTE FUNCTION baobab_native.forbid_placed_ledger_rewrite();

-- A posted header must retain the original contracting/financial facts. Native
-- bookkeeping-only changes (e.g. Posted, Processed flags) remain possible;
-- changing DocStatus away from completed requires a separately catalogued
-- and independently qualified reversal operation, not a direct UPDATE.
-- All provenance-bearing placed headers, including drafts, refuse DELETE.
CREATE FUNCTION baobab_native.forbid_governed_header_history_rewrite()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  original jsonb;
  incoming jsonb;
  key text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF baobab_native.client_is_placed(OLD.ad_client_id::integer) THEN
      RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: placed source document history cannot be deleted'
        USING ERRCODE = '42501';
    END IF;
    RETURN OLD;
  END IF;
  IF NOT (baobab_native.client_is_placed(OLD.ad_client_id::integer)
          OR baobab_native.client_is_placed(NEW.ad_client_id::integer)) THEN
    RETURN NEW;
  END IF;
  -- Existing N0002 guards all changes of client and org, even on drafts.
  IF OLD.docstatus IN ('CO', 'CL') THEN
    IF NEW.docstatus IS DISTINCT FROM OLD.docstatus THEN
      RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: completed document state is immutable without a reversal class'
        USING ERRCODE = '42501';
    END IF;
    original := to_jsonb(OLD);
    incoming := to_jsonb(NEW);
    -- Work across the real per-document iDempiere schemas without pretending
    -- every header has every possible column. Missing keys compare as NULL.
    FOREACH key IN ARRAY ARRAY[
      'ad_client_id', 'ad_org_id', 'dateacct', 'c_doctype_id',
      'c_doctypetarget_id', 'issotrx', 'movementtype', 'isreceipt',
      'isonline', 'c_bpartner_id', 'c_currency_id', 'grandtotal',
      'totallines', 'payamt', 'c_invoice_id', 'c_paymentterm_id',
      'c_charge_id', 'c_tax_id', 'dateinvoiced', 'dateordered',
      'c_acctschema_id', 'c_conversiontype_id', 'c_bankaccount_id',
      'totaldr', 'totalcr', 'controlamt'
    ] LOOP
      IF original -> key IS DISTINCT FROM incoming -> key THEN
        RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: completed document financial facts are immutable'
          USING ERRCODE = '42501';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE
  doc text;
BEGIN
  FOREACH doc IN ARRAY ARRAY[
    'gl_journal', 'c_invoice', 'c_payment', 'c_allocationhdr',
    'm_inout', 'c_order', 'c_bankstatement', 'c_cash'
  ] LOOP
    IF to_regclass('adempiere.' || doc) IS NULL THEN
      RAISE EXCEPTION 'N0010 requires actual iDempiere header: %', doc;
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_protect_governed_header_history
      BEFORE UPDATE OR DELETE ON adempiere.%I FOR EACH ROW
      EXECUTE FUNCTION baobab_native.forbid_governed_header_history_rewrite()', doc);
  END LOOP;
END $$;

-- iDempiere legitimately updates operational progress counters (e.g.
-- QtyDelivered/QtyInvoiced on a completed sales order). Do NOT freeze all
-- line columns. Protect only original quantity, price, charge, product,
-- allocation, warehouse and parent-identity facts. The header's completion
-- and the line mutation are assessed in the SAME database transaction.
CREATE FUNCTION baobab_native.forbid_completed_line_financial_rewrite()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  former jsonb;
  proposed jsonb;
  original_parent integer;
  new_parent integer;
  previous_status text;
  current_status text;
  key text;
  protected_keys text[] := string_to_array(TG_ARGV[2], ',');
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
      RETURN NEW;
    END IF;
    proposed := to_jsonb(NEW);
    new_parent := (proposed ->> TG_ARGV[1])::numeric::integer;
  ELSE
    former := to_jsonb(OLD);
    original_parent := (former ->> TG_ARGV[1])::numeric::integer;
    IF TG_OP = 'UPDATE' THEN
      proposed := to_jsonb(NEW);
      new_parent := (proposed ->> TG_ARGV[1])::numeric::integer;
    END IF;
  END IF;
  IF TG_OP <> 'INSERT'
     AND baobab_native.client_is_placed(OLD.ad_client_id::integer)
     AND original_parent IS NOT NULL THEN
    EXECUTE format('SELECT docstatus::text FROM adempiere.%I WHERE %I = $1',
                   TG_ARGV[0], TG_ARGV[1])
      INTO previous_status USING original_parent;
  END IF;
  IF TG_OP <> 'DELETE'
     AND baobab_native.client_is_placed(NEW.ad_client_id::integer)
     AND new_parent IS NOT NULL THEN
    EXECUTE format('SELECT docstatus::text FROM adempiere.%I WHERE %I = $1',
                   TG_ARGV[0], TG_ARGV[1])
      INTO current_status USING new_parent;
  END IF;
  IF previous_status IN ('CO', 'CL') OR current_status IN ('CO', 'CL') THEN
    IF TG_OP <> 'UPDATE' THEN
      RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: completed document cannot gain or lose financial lines'
        USING ERRCODE = '42501';
    END IF;
    -- Retain non-financial operational counters; protect the closed input
    -- facts and the complete client/org/parent provenance.
    FOREACH key IN ARRAY protected_keys LOOP
      IF former -> key IS DISTINCT FROM proposed -> key THEN
        RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: completed document line financial facts are immutable'
          USING ERRCODE = '42501';
      END IF;
    END LOOP;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE
  spec text[];
BEGIN
  FOREACH spec SLICE 1 IN ARRAY ARRAY[
    ARRAY['gl_journalline', 'gl_journal', 'gl_journal_id',
          'ad_client_id,ad_org_id,gl_journal_id,amtsourcedr,amtsourcecr,amtacctdr,amtacctcr,c_currency_id,c_validcombination_id'],
    ARRAY['c_invoiceline', 'c_invoice', 'c_invoice_id',
          'ad_client_id,ad_org_id,c_invoice_id,qtyinvoiced,priceactual,priceentered,pricelist,linenetamt,taxamt,m_product_id,c_uom_id,c_tax_id,c_orderline_id,c_charge_id'],
    ARRAY['c_orderline', 'c_order', 'c_order_id',
          'ad_client_id,ad_org_id,c_order_id,qtyordered,priceactual,priceentered,pricelist,linenetamt,m_product_id,c_uom_id,c_tax_id,c_charge_id,m_attributesetinstance_id'],
    ARRAY['m_inoutline', 'm_inout', 'm_inout_id',
          'ad_client_id,ad_org_id,m_inout_id,movementqty,m_product_id,m_locator_id,m_attributesetinstance_id,c_orderline_id'],
    ARRAY['c_allocationline', 'c_allocationhdr', 'c_allocationhdr_id',
          'ad_client_id,ad_org_id,c_allocationhdr_id,amount,discountamt,writeoffamt,overunderamt,c_invoice_id,c_payment_id']
  ] LOOP
    IF to_regclass('adempiere.' || spec[1]) IS NULL THEN
      RAISE EXCEPTION 'N0010 requires actual iDempiere financial line: %', spec[1];
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_protect_completed_financial_line
      BEFORE INSERT OR UPDATE OR DELETE ON adempiere.%I FOR EACH ROW
      EXECUTE FUNCTION baobab_native.forbid_completed_line_financial_rewrite(%L, %L, %L)',
      spec[1], spec[2], spec[3], spec[4]);
  END LOOP;
END $$;
