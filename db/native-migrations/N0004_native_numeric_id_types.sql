-- P0-04B ERP (Gate D finding): real iDempiere stores every *_ID column as
-- NUMERIC(10), not integer. N0002/N0003 passed NEW.ad_client_id etc. straight
-- into integer-typed helpers, so on a real iDempiere database every governed
-- document insert failed with "function client_is_placed(numeric) does not
-- exist". That failure denied (it never granted), but it denied valid work.
--
-- Forward fix: redefine the four trigger functions with explicit integer
-- casts at each call site. iDempiere IDs are Java ints, so the cast is exact.
-- The helper signatures, triggers and policy are unchanged.

CREATE OR REPLACE FUNCTION baobab_native.record_document_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE placement baobab_native.native_placement; record_id integer;
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  placement := baobab_native.current_placement(NEW.ad_client_id::integer, NEW.ad_org_id::integer);
  IF placement.placement_id IS NULL THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: no current placement for AD_Client %/AD_Org %',
      NEW.ad_client_id, NEW.ad_org_id USING ERRCODE = '42501';
  END IF;
  record_id := (to_jsonb(NEW) ->> TG_ARGV[1])::numeric::integer;
  INSERT INTO baobab_native.document_provenance
    (native_table, record_id, ad_client_id, ad_org_id, placement_id, placement_version)
  VALUES (TG_ARGV[0], record_id, NEW.ad_client_id::integer, NEW.ad_org_id::integer,
          placement.placement_id, placement.version);
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION baobab_native.forbid_document_org_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.ad_client_id, NEW.ad_org_id) IS DISTINCT FROM (OLD.ad_client_id, OLD.ad_org_id)
     AND (baobab_native.client_is_placed(OLD.ad_client_id::integer)
          OR baobab_native.client_is_placed(NEW.ad_client_id::integer)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: a governed document cannot change client or organisation'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION baobab_native.fact_acct_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_table text;
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id::integer) THEN
    RETURN NULL;
  END IF;
  SELECT t.tablename INTO source_table FROM adempiere.ad_table t WHERE t.ad_table_id = NEW.ad_table_id;
  IF source_table IS NULL
     OR NOT baobab_native.has_current_attribution(NEW.ad_client_id::integer, source_table,
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
  IF NOT baobab_native.has_current_attribution(NEW.ad_client_id::integer, TG_ARGV[0], record_id) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: document completion without current authority at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;
