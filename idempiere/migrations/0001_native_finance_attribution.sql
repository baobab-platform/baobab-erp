-- LA-05D9: deploy IN THE SAME PostgreSQL database/transaction domain
-- as native iDempiere Trx, never only in the baobab-app store.
-- Required before accepting ANY native protected financial operation.
BEGIN;
CREATE SCHEMA IF NOT EXISTS baobab_native;

CREATE TABLE IF NOT EXISTS baobab_native.finance_authority_attribution (
  attribution_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id text NOT NULL CHECK (length(btrim(tenant_id)) BETWEEN 3 AND 100),
  context_id uuid NOT NULL,
  operating_organisation_id uuid NOT NULL,
  responsible_legal_entity_id text NOT NULL CHECK (length(btrim(responsible_legal_entity_id)) BETWEEN 3 AND 160),
  cp_mandate_id uuid NOT NULL,
  evidence_reference text NOT NULL CHECK (length(btrim(evidence_reference)) BETWEEN 3 AND 256),
  native_table text NOT NULL CHECK (native_table ~ '^[A-Za-z_]{3,90}$'),
  ad_client_id integer NOT NULL CHECK (ad_client_id > 0),
  ad_org_id integer NOT NULL CHECK (ad_org_id > 0),
  native_record_id integer NOT NULL CHECK (native_record_id >= 0),
  action_name text NOT NULL CHECK (length(btrim(action_name)) BETWEEN 3 AND 120),
  native_transaction_name text NOT NULL CHECK (length(btrim(native_transaction_name)) BETWEEN 3 AND 256),
  correlation_id uuid NOT NULL UNIQUE,
  recorded_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE INDEX IF NOT EXISTS finance_authority_attribution_scope_idx
ON baobab_native.finance_authority_attribution
  (ad_client_id, ad_org_id, native_table, native_record_id, recorded_at);

CREATE OR REPLACE FUNCTION baobab_native.prevent_financial_history_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable native financial attribution cannot be modified or deleted'
    USING ERRCODE='42501';
END $$;

DROP TRIGGER IF EXISTS finance_authority_no_rewrite
 ON baobab_native.finance_authority_attribution;
CREATE TRIGGER finance_authority_no_rewrite
BEFORE UPDATE OR DELETE ON baobab_native.finance_authority_attribution
FOR EACH ROW EXECUTE FUNCTION baobab_native.prevent_financial_history_mutation();

REVOKE ALL ON SCHEMA baobab_native FROM PUBLIC;
REVOKE ALL ON baobab_native.finance_authority_attribution FROM PUBLIC;
-- DB operator MUST grant INSERT and the narrowly scoped SELECT needed for
-- reconciliation to the iDempiere application role; NEVER UPDATE/DELETE or
-- BYPASSRLS. Enforce iDempiere company/client on native DB grants and
-- independently reject direct SQL bypass of ModelValidationEngine.
COMMIT;
