-- Read-only verification of actual enabled PostgreSQL guards. A migration
-- receipt or health marker alone is NOT proof of current installed controls.
-- This query returns one integer: missing mandatory migration/trigger count.
WITH required_migrations(filename) AS (
  VALUES
    ('native/N0010_posted_financial_history_integrity.sql'),
    ('native/N0011_uncatalogued_finance_configuration.sql'),
    ('native/N0012_no_truncate_financial_history.sql'),
    ('native/N0013_historical_company_org_identity.sql')
),
required_triggers(schema_name, relation_name, trigger_name) AS (
  VALUES
    ('baobab_native', 'native_placement', 'native_placement_guard'),
    ('baobab_native', 'native_placement', 'native_placement_org_owner_guard'),
    ('baobab_native', 'native_placement', 'baobab_immutable_history_no_truncate'),
    ('baobab_native', 'document_provenance', 'document_provenance_immutable'),
    ('baobab_native', 'document_provenance', 'baobab_immutable_history_no_truncate'),
    ('baobab_native', 'finance_authority_attribution', 'finance_attribution_insert_guard'),
    ('baobab_native', 'finance_authority_attribution', 'finance_authority_no_rewrite'),
    ('baobab_native', 'finance_authority_attribution', 'baobab_immutable_history_no_truncate'),
    ('baobab_native', 'derived_write_attribution', 'derived_write_insert_guard'),
    ('baobab_native', 'derived_write_attribution', 'derived_write_immutable'),
    ('baobab_native', 'derived_write_attribution', 'baobab_immutable_history_no_truncate'),
    ('baobab_native', 'payment_execution_evidence', 'payment_evidence_insert_guard'),
    ('baobab_native', 'payment_execution_evidence', 'payment_evidence_immutable'),
    ('baobab_native', 'payment_execution_evidence', 'baobab_immutable_history_no_truncate'),
    ('baobab_native', 'payment_execution_binding', 'payment_binding_immutable'),
    ('baobab_native', 'payment_execution_binding', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'fact_acct', 'baobab_fact_acct_commit_fence'),
    ('adempiere', 'fact_acct', 'baobab_ledger_immutable_history'),
    ('adempiere', 'ad_org', 'baobab_placed_ad_org_change_guard'),
    ('adempiere', 'ad_org', 'baobab_placed_ad_org_key_history_guard'),
    ('adempiere', 'ad_org', 'baobab_native_org_no_truncate'),
    ('adempiere', 'ad_client', 'baobab_placed_ad_client_history_guard'),
    ('adempiere', 'ad_client', 'baobab_native_company_no_truncate'),
    ('adempiere', 'gl_journal', 'baobab_protect_governed_header_history'),
    ('adempiere', 'c_invoice', 'baobab_protect_governed_header_history'),
    ('adempiere', 'c_payment', 'baobab_protect_governed_header_history'),
    ('adempiere', 'c_allocationhdr', 'baobab_protect_governed_header_history'),
    ('adempiere', 'm_inout', 'baobab_protect_governed_header_history'),
    ('adempiere', 'c_order', 'baobab_protect_governed_header_history'),
    ('adempiere', 'c_bankstatement', 'baobab_protect_governed_header_history'),
    ('adempiere', 'c_cash', 'baobab_protect_governed_header_history'),
    ('adempiere', 'gl_journalline', 'baobab_protect_completed_financial_line'),
    ('adempiere', 'c_invoiceline', 'baobab_protect_completed_financial_line'),
    ('adempiere', 'c_orderline', 'baobab_protect_completed_financial_line'),
    ('adempiere', 'm_inoutline', 'baobab_protect_completed_financial_line'),
    ('adempiere', 'c_allocationline', 'baobab_protect_completed_financial_line'),
    ('adempiere', 'c_acctschema', 'baobab_uncatalogued_finance_configuration'),
    ('adempiere', 'c_elementvalue', 'baobab_uncatalogued_finance_configuration'),
    ('adempiere', 'c_validcombination', 'baobab_uncatalogued_finance_configuration'),
    ('adempiere', 'c_tax', 'baobab_uncatalogued_finance_configuration'),
    ('adempiere', 'c_tax_acct', 'baobab_uncatalogued_finance_configuration'),
    ('adempiere', 'c_bankaccount', 'baobab_uncatalogued_finance_configuration'),
    ('adempiere', 'fact_acct', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'gl_journal', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'gl_journalline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_invoice', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_invoiceline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_order', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_orderline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'm_inout', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'm_inoutline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_payment', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_allocationhdr', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_allocationline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_bankstatement', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_bankstatementline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_cash', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_cashline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'm_matchpo', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'm_matchinv', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'm_costdetail', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'm_cost', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_payselection', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_payselectionline', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_payselectioncheck', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_acctschema', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_elementvalue', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_validcombination', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_tax', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_tax_acct', 'baobab_immutable_history_no_truncate'),
    ('adempiere', 'c_bankaccount', 'baobab_immutable_history_no_truncate')
),
missing_migrations AS (
  SELECT m.filename FROM required_migrations m
  WHERE NOT EXISTS (SELECT 1 FROM baobab.schema_migrations history
                    WHERE history.filename=m.filename)
),
missing_triggers AS (
  SELECT r.* FROM required_triggers r
  LEFT JOIN pg_namespace ns ON ns.nspname=r.schema_name
  LEFT JOIN pg_class rel ON rel.relnamespace=ns.oid AND rel.relname=r.relation_name
  LEFT JOIN pg_trigger tg ON tg.tgrelid=rel.oid
                         AND tg.tgname=r.trigger_name
                         AND tg.tgenabled='O' AND NOT tg.tgisinternal
  WHERE tg.oid IS NULL
)
SELECT (SELECT count(*) FROM missing_migrations)
     + (SELECT count(*) FROM missing_triggers)
     + CASE WHEN current_setting('server_version_num')::integer BETWEEN 170000 AND 179999 THEN 0 ELSE 1 END
     AS missing;
