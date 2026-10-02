-- ADR-ERP-008: the Finance-approved, ERP-owned financial configuration baseline of a legal entity.
--
-- Control Plane may retain canonical financial metadata (legal entity, expected functional currency, jurisdiction,
-- engine instance) but detailed accounting configuration is ERP's. It is Finance's decision, so a baseline exists only
-- with a named accountable approver and evidence, and is never defaulted or inferred by engineers.
--
-- * Append-only and versioned per legal entity: a change is a new version; history is kept and never edited.
-- * effective_from dates when it applies; the baseline in force on a date is the one with the latest effective_from
--   (then the highest version) not after that date.
-- * approved_by must be a named person: not blank, not a REQUIRED_* placeholder, not a synthetic actor such as
--   'system'. (Verifying that the named person holds Finance authority is IAM's, not this table's.)

CREATE TABLE baobab.financial_configuration_baseline (
    legal_entity_id             TEXT        NOT NULL,
    version                     INTEGER     NOT NULL CHECK (version >= 1),
    functional_currency         TEXT        NOT NULL CHECK (functional_currency ~ '^[A-Z]{3}$'),
    fiscal_year_start_month     SMALLINT    NOT NULL CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    chart_of_accounts_template  TEXT        NOT NULL CHECK (btrim(chart_of_accounts_template) <> '' AND chart_of_accounts_template NOT LIKE 'REQUIRED\_%'),
    accounting_schema           TEXT        NOT NULL CHECK (btrim(accounting_schema) <> '' AND accounting_schema NOT LIKE 'REQUIRED\_%'),
    tax_profile                 TEXT        NOT NULL CHECK (btrim(tax_profile) <> '' AND tax_profile NOT LIKE 'REQUIRED\_%'),
    costing_method              TEXT        NOT NULL CHECK (btrim(costing_method) <> '' AND costing_method NOT LIKE 'REQUIRED\_%'),
    effective_from              DATE        NOT NULL,
    approved_by                 TEXT        NOT NULL CHECK (
        btrim(approved_by) <> '' AND approved_by NOT LIKE 'REQUIRED\_%'
        AND lower(btrim(approved_by)) NOT IN ('system', 'service', 'bootstrap', 'automation', 'auto', 'unknown', 'n/a', 'none')),
    approved_at                 TIMESTAMPTZ NOT NULL,
    evidence_reference          TEXT        NOT NULL CHECK (btrim(evidence_reference) <> '' AND evidence_reference NOT LIKE 'REQUIRED\_%'),
    recorded_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (legal_entity_id, version),
    CHECK (btrim(legal_entity_id) <> '')
);

CREATE INDEX financial_configuration_baseline_effective
    ON baobab.financial_configuration_baseline (legal_entity_id, effective_from DESC, version DESC);

CREATE FUNCTION baobab.financial_configuration_baseline_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'financial_configuration_baseline is append-only: record a new version instead of changing or deleting one'
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER financial_configuration_baseline_no_update_delete
    BEFORE UPDATE OR DELETE ON baobab.financial_configuration_baseline
    FOR EACH ROW EXECUTE FUNCTION baobab.financial_configuration_baseline_append_only();
