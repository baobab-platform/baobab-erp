-- ADR-ERP-023 BP-04: experimental, non-activating employment proposal history.
-- Install ONLY in a disposable PostgreSQL 17 iDempiere database via
-- db/migrate-people-experimental.sh. No real employee PII or active workforce
-- state; no AD_Employee, C_BPartner or payroll native records are created.
DO $$
BEGIN
  IF current_setting('server_version_num')::integer NOT BETWEEN 170000 AND 179999 THEN
    RAISE EXCEPTION 'Baobab People BP-04 requires PostgreSQL major 17';
  END IF;
  IF to_regclass('baobab.schema_migrations') IS NULL THEN
    RAISE EXCEPTION 'Apply baobab-erp application migrations first';
  END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS baobab_people;
REVOKE ALL ON SCHEMA baobab_people FROM PUBLIC;

CREATE TABLE baobab_people.employment_proposal (
  tenant_id text NOT NULL CHECK (tenant_id ~ '^[A-Za-z0-9_.:-]{3,160}$'),
  legal_employer_id text NOT NULL CHECK (legal_employer_id ~ '^[A-Za-z0-9_.:-]{3,160}$'),
  person_ref text NOT NULL CHECK (person_ref ~ '^[A-Za-z0-9_.:/-]{3,160}$'),
  version integer NOT NULL CHECK (version >= 1),
  effective_from date NOT NULL,
  effective_until date,
  work_jurisdiction text NOT NULL CHECK (work_jurisdiction ~ '^[A-Z]{2}$'),
  tax_jurisdiction text NOT NULL CHECK (tax_jurisdiction ~ '^[A-Z]{2}$'),
  pay_currency text NOT NULL CHECK (pay_currency ~ '^[A-Z]{3}$'),
  contract_evidence_ref text NOT NULL CHECK (contract_evidence_ref ~ '^[A-Za-z0-9_.:/-]{3,160}$'),
  writer_principal_ref text NOT NULL CHECK (writer_principal_ref ~ '^[A-Za-z0-9_.:/-]{3,160}$'),
  state text NOT NULL DEFAULT 'PROPOSED' CHECK (state = 'PROPOSED'),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, legal_employer_id, person_ref, version),
  CHECK (effective_until IS NULL OR effective_until > effective_from)
);
REVOKE ALL ON baobab_people.employment_proposal FROM PUBLIC;
CREATE INDEX employment_proposal_effective_lookup
  ON baobab_people.employment_proposal
  (tenant_id, legal_employer_id, person_ref, effective_from DESC, version DESC);

CREATE FUNCTION baobab_people.employment_proposal_before_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior baobab_people.employment_proposal%ROWTYPE;
BEGIN
  -- Serialize all writers to this employer/person. No lost version may pass
  -- even when two independent connections read the same prior value.
  PERFORM pg_advisory_xact_lock(hashtextextended(
    jsonb_build_array('people-employment', NEW.tenant_id, NEW.legal_employer_id, NEW.person_ref)::text, 0));
  SELECT * INTO prior FROM baobab_people.employment_proposal
   WHERE tenant_id = NEW.tenant_id AND legal_employer_id = NEW.legal_employer_id
     AND person_ref = NEW.person_ref
   ORDER BY version DESC LIMIT 1;
  IF (prior.version IS NULL AND NEW.version <> 1)
     OR (prior.version IS NOT NULL AND
         (NEW.version <> prior.version + 1 OR NEW.effective_from <= prior.effective_from
           OR (prior.effective_until IS NOT NULL AND NEW.effective_from < prior.effective_until))) THEN
    RAISE EXCEPTION 'BAOBAB_PEOPLE_DENIED: nonconsecutive or overlapping employment proposal'
      USING ERRCODE = '23514';
  END IF;
  NEW.recorded_at := clock_timestamp();
  RETURN NEW;
END $$;
CREATE TRIGGER employment_proposal_cas
  BEFORE INSERT ON baobab_people.employment_proposal
  FOR EACH ROW EXECUTE FUNCTION baobab_people.employment_proposal_before_insert();

CREATE FUNCTION baobab_people.refuse_history_rewrite()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'BAOBAB_PEOPLE_DENIED: proposal and evidence history are append-only'
    USING ERRCODE = '42501';
END $$;
CREATE TRIGGER employment_proposal_immutable
  BEFORE UPDATE OR DELETE ON baobab_people.employment_proposal
  FOR EACH ROW EXECUTE FUNCTION baobab_people.refuse_history_rewrite();
CREATE TRIGGER employment_proposal_no_truncate
  BEFORE TRUNCATE ON baobab_people.employment_proposal
  FOR EACH STATEMENT EXECUTE FUNCTION baobab_people.refuse_history_rewrite();
