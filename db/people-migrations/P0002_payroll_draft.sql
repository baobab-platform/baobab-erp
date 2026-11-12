-- ADR-ERP-023 BP-04: only a non-activating *metadata* draft registry.
-- NEVER a payroll calculation, approval, statutory fact, native GL posting
-- or bank-release authority. No earnings, deductions, employee names or bank
-- details are stored here. No production migration path is enabled.
CREATE TABLE baobab_people.payroll_draft (
  tenant_id text NOT NULL CHECK (tenant_id ~ '^[A-Za-z0-9_.:-]{3,160}$'),
  legal_employer_id text NOT NULL CHECK (legal_employer_id ~ '^[A-Za-z0-9_.:-]{3,160}$'),
  run_ref text NOT NULL CHECK (run_ref ~ '^[A-Za-z0-9_.:/-]{3,160}$'),
  version integer NOT NULL CHECK (version >= 1),
  maker_ref text NOT NULL CHECK (maker_ref ~ '^[A-Za-z0-9_.:/-]{3,160}$'),
  period_from date NOT NULL,
  period_until date NOT NULL,
  statutory_jurisdiction text NOT NULL CHECK (statutory_jurisdiction ~ '^[A-Z]{2}$'),
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  rule_pack_sha256 text NOT NULL CHECK (rule_pack_sha256 ~ '^[0-9a-f]{64}$'),
  correction_of_run_ref text,
  state text NOT NULL DEFAULT 'DRAFT' CHECK (state = 'DRAFT'),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, legal_employer_id, run_ref, version),
  CHECK (period_until >= period_from),
  CHECK (correction_of_run_ref IS NULL OR
         (correction_of_run_ref ~ '^[A-Za-z0-9_.:/-]{3,160}$' AND correction_of_run_ref <> run_ref))
);
REVOKE ALL ON baobab_people.payroll_draft FROM PUBLIC;
CREATE INDEX payroll_draft_employer_period
  ON baobab_people.payroll_draft
  (tenant_id, legal_employer_id, period_from, period_until);

CREATE FUNCTION baobab_people.payroll_draft_before_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior baobab_people.payroll_draft%ROWTYPE;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(
    jsonb_build_array('people-draft', NEW.tenant_id, NEW.legal_employer_id, NEW.run_ref)::text, 0));
  SELECT * INTO prior FROM baobab_people.payroll_draft
   WHERE tenant_id = NEW.tenant_id AND legal_employer_id = NEW.legal_employer_id
     AND run_ref = NEW.run_ref ORDER BY version DESC LIMIT 1;
  IF (prior.version IS NULL AND NEW.version <> 1)
     OR (prior.version IS NOT NULL AND (NEW.version <> prior.version + 1
       OR NEW.period_from <> prior.period_from
       OR NEW.period_until <> prior.period_until
       OR NEW.statutory_jurisdiction <> prior.statutory_jurisdiction
       OR NEW.currency <> prior.currency
       OR NEW.correction_of_run_ref IS DISTINCT FROM prior.correction_of_run_ref)) THEN
    RAISE EXCEPTION 'BAOBAB_PEOPLE_DENIED: invalid draft version or changed employer/period'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.correction_of_run_ref IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM baobab_people.payroll_draft previous
     WHERE previous.tenant_id = NEW.tenant_id
       AND previous.legal_employer_id = NEW.legal_employer_id
       AND previous.run_ref = NEW.correction_of_run_ref
       AND previous.period_from <= NEW.period_from
  ) THEN
    RAISE EXCEPTION 'BAOBAB_PEOPLE_DENIED: no prior employer-scoped payroll run to correct'
      USING ERRCODE = '23514';
  END IF;
  NEW.recorded_at := clock_timestamp();
  RETURN NEW;
END $$;
CREATE TRIGGER payroll_draft_cas
  BEFORE INSERT ON baobab_people.payroll_draft
  FOR EACH ROW EXECUTE FUNCTION baobab_people.payroll_draft_before_insert();
CREATE TRIGGER payroll_draft_immutable
  BEFORE UPDATE OR DELETE ON baobab_people.payroll_draft
  FOR EACH ROW EXECUTE FUNCTION baobab_people.refuse_history_rewrite();
CREATE TRIGGER payroll_draft_no_truncate
  BEFORE TRUNCATE ON baobab_people.payroll_draft
  FOR EACH STATEMENT EXECUTE FUNCTION baobab_people.refuse_history_rewrite();
