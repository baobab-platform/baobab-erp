-- P0-04B ERP (ADR-SHARED-034, ADR-ERP-022): historical attribution and the
-- database COMMIT fence for placed AD_Clients.
--
-- 1. Each authorised native write records, in the SAME transaction, the CP
--    decision, mandate lineage, placement and Finance baseline it relied on,
--    so "which legal actor applied to this posting at time T" is answered
--    from stored references (ADR-BCP-027 §10.2), never from today's mapping.
-- 2. Fact_Acct inserts and document completion (DocStatus -> CO/CL) of a
--    placed client are checked at COMMIT: the transaction must hold a current
--    attribution for the same source document. Direct SQL, import, scheduler
--    or any route that bypasses the JVM veto therefore rolls back, and so does
--    a posting transaction that outlives its authority lease.
--
-- Freshness policy: a CP decision is usable until
-- min(expires_at, ERP receipt + 30 seconds); a revocation therefore takes
-- effect within 30 seconds. Database atomicity and CP freshness are separate
-- guarantees; both are required.
BEGIN;

ALTER TABLE baobab_native.finance_authority_attribution
  ADD COLUMN decision_id uuid,
  ADD COLUMN operation_class text,
  ADD COLUMN source_table text,
  ADD COLUMN source_record_id integer,
  ADD COLUMN supersedes_mandate_id uuid,
  ADD COLUMN mandate_effective_from timestamptz,
  ADD COLUMN authority_expires_at timestamptz,
  ADD COLUMN placement_id uuid,
  ADD COLUMN placement_version integer,
  ADD COLUMN finance_baseline_legal_entity_id text,
  ADD COLUMN finance_baseline_version integer,
  ADD COLUMN received_at timestamptz DEFAULT clock_timestamp(),
  ADD COLUMN txid bigint DEFAULT txid_current();

-- Every attribution written from now on is complete. Pre-existing LA-05D9
-- rows (if any) keep their original shape and are never rewritten.
ALTER TABLE baobab_native.finance_authority_attribution
  ADD CONSTRAINT finance_authority_attribution_p004b_complete CHECK (
    decision_id IS NOT NULL
    AND operation_class ~ '^erp\.[a-z-]+\.[a-z-]+$'
    AND source_table ~ '^[A-Za-z_]{3,60}$' AND source_record_id >= 0
    AND mandate_effective_from IS NOT NULL
    AND authority_expires_at IS NOT NULL
    AND placement_id IS NOT NULL AND placement_version >= 1
    AND finance_baseline_legal_entity_id = responsible_legal_entity_id
    AND finance_baseline_version >= 1
    AND received_at IS NOT NULL AND txid IS NOT NULL
    AND authority_expires_at <= received_at + interval '30 seconds') NOT VALID,
  ADD CONSTRAINT finance_authority_attribution_placement_fk
    FOREIGN KEY (placement_id, placement_version)
    REFERENCES baobab_native.native_placement (placement_id, version) NOT VALID;

CREATE INDEX finance_authority_attribution_txid_idx
  ON baobab_native.finance_authority_attribution (txid, ad_client_id, source_table, source_record_id);
CREATE INDEX finance_authority_attribution_decision_idx
  ON baobab_native.finance_authority_attribution (decision_id);

-- Insert guard: the attribution must be current by the DATABASE clock and
-- bound to the in-force placement of its native org, with the same tenant,
-- Organisation and legal entity.
CREATE FUNCTION baobab_native.finance_attribution_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE placement baobab_native.native_placement;
BEGIN
  NEW.received_at := clock_timestamp();
  NEW.txid := txid_current();
  IF NEW.authority_expires_at IS NULL OR NEW.authority_expires_at <= NEW.received_at THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: posting authority expired before attribution'
      USING ERRCODE = '42501';
  END IF;
  NEW.authority_expires_at := LEAST(NEW.authority_expires_at, NEW.received_at + interval '30 seconds');
  -- The placement is the source document's (a ledger line's own AD_Org can
  -- differ); it must be in force now and belong to the same native client.
  SELECT p.* INTO placement FROM baobab_native.native_placement p
   WHERE p.placement_id = NEW.placement_id AND p.ad_client_id = NEW.ad_client_id
     AND p.effective_from <= clock_timestamp()
     AND (p.effective_to IS NULL OR p.effective_to > clock_timestamp());
  IF placement.placement_id IS NULL
     OR placement.version <> NEW.placement_version
     OR placement.tenant_id <> NEW.tenant_id
     OR placement.operating_organisation_id <> NEW.operating_organisation_id
     OR placement.legal_entity_id <> NEW.responsible_legal_entity_id THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: attribution does not match the current placement'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER finance_attribution_insert_guard BEFORE INSERT
  ON baobab_native.finance_authority_attribution FOR EACH ROW
  EXECUTE FUNCTION baobab_native.finance_attribution_insert_guard();

-- True when THIS transaction holds a still-current attribution for the
-- source document, under the database clock.
CREATE FUNCTION baobab_native.has_current_attribution(p_client integer, p_table text, p_record integer)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM baobab_native.finance_authority_attribution a
     WHERE a.txid = txid_current() AND a.ad_client_id = p_client
       AND a.decision_id IS NOT NULL
       AND lower(a.source_table) = lower(p_table) AND a.source_record_id = p_record
       AND a.authority_expires_at > clock_timestamp())
$$;

CREATE FUNCTION baobab_native.fact_acct_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_table text;
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id) THEN
    RETURN NULL;
  END IF;
  SELECT t.tablename INTO source_table FROM adempiere.ad_table t WHERE t.ad_table_id = NEW.ad_table_id;
  IF source_table IS NULL
     OR NOT baobab_native.has_current_attribution(NEW.ad_client_id, source_table, NEW.record_id) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: ledger posting without current authority at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER baobab_fact_acct_commit_fence AFTER INSERT ON adempiere.fact_acct
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION baobab_native.fact_acct_commit_fence();

CREATE FUNCTION baobab_native.document_completion_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE record_id integer;
BEGIN
  IF NEW.docstatus NOT IN ('CO', 'CL') OR OLD.docstatus IN ('CO', 'CL')
     OR NOT baobab_native.client_is_placed(NEW.ad_client_id) THEN
    RETURN NULL;
  END IF;
  record_id := (to_jsonb(NEW) ->> TG_ARGV[1])::integer;
  IF NOT baobab_native.has_current_attribution(NEW.ad_client_id, TG_ARGV[0], record_id) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: document completion without current authority at COMMIT'
      USING ERRCODE = '42501';
  END IF;
  RETURN NULL;
END $$;

DO $$
DECLARE doc record;
BEGIN
  FOR doc IN SELECT * FROM (VALUES
      ('GL_Journal', 'gl_journal'), ('C_Invoice', 'c_invoice'), ('C_Payment', 'c_payment'),
      ('C_AllocationHdr', 'c_allocationhdr'), ('M_InOut', 'm_inout'), ('C_Order', 'c_order'),
      ('C_BankStatement', 'c_bankstatement'), ('C_Cash', 'c_cash')) AS t(native_table, relation)
  LOOP
    EXECUTE format('CREATE CONSTRAINT TRIGGER baobab_completion_commit_fence AFTER UPDATE OF docstatus
      ON adempiere.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION baobab_native.document_completion_commit_fence(%L, %L)',
      doc.relation, doc.native_table, doc.relation || '_id');
  END LOOP;
END $$;

COMMIT;
