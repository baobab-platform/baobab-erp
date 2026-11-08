-- ERP native ADR-002/008/011/017/019/022: immutable history cannot
-- be destroyed with TRUNCATE. Row-level DELETE triggers are NOT fired by
-- PostgreSQL TRUNCATE (including TRUNCATE ... CASCADE).
--
-- This is a total prohibition on truncating the governed records, native
-- ledger and accounting configuration tables, even when a table is empty.
-- Any legitimate decommissioning/retention workflow must use its own
-- independently governed procedures and prove custody/retention first.
-- No new CP authority is granted here; no existing triggers are disabled.

CREATE FUNCTION baobab_native.forbid_history_truncate()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: TRUNCATE bypasses immutable financial and legal-actor history (%)',
    TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME
    USING ERRCODE = '42501';
END $$;

DO $$
DECLARE
  relation text;
BEGIN
  FOREACH relation IN ARRAY ARRAY[
    'native_placement', 'document_provenance',
    'finance_authority_attribution', 'derived_write_attribution',
    'payment_execution_evidence', 'payment_execution_binding'
  ] LOOP
    IF to_regclass('baobab_native.' || relation) IS NULL THEN
      RAISE EXCEPTION 'N0012 missing mandatory evidence/history relation: %', relation;
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_immutable_history_no_truncate
      BEFORE TRUNCATE ON baobab_native.%I
      FOR EACH STATEMENT EXECUTE FUNCTION baobab_native.forbid_history_truncate()', relation);
  END LOOP;

  FOREACH relation IN ARRAY ARRAY[
    'fact_acct', 'gl_journal', 'gl_journalline', 'c_invoice',
    'c_invoiceline', 'c_order', 'c_orderline', 'm_inout',
    'm_inoutline', 'c_payment', 'c_allocationhdr',
    'c_allocationline', 'c_bankstatement', 'c_bankstatementline',
    'c_cash', 'c_cashline', 'm_matchpo', 'm_matchinv',
    'm_costdetail', 'm_cost', 'c_payselection',
    'c_payselectionline', 'c_payselectioncheck',
    'c_acctschema', 'c_acctschema_default', 'c_acctschema_gl',
    'c_elementvalue', 'c_validcombination',
    'c_tax', 'c_tax_acct', 'c_bankaccount', 'c_bankaccount_acct'
  ] LOOP
    IF to_regclass('adempiere.' || relation) IS NULL THEN
      RAISE EXCEPTION 'N0012 missing mandatory native ERP relation: %', relation;
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_immutable_history_no_truncate
      BEFORE TRUNCATE ON adempiere.%I
      FOR EACH STATEMENT EXECUTE FUNCTION baobab_native.forbid_history_truncate()', relation);
  END LOOP;
END $$;
