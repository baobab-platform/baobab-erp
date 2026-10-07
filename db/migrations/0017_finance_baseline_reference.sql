-- ERP-FB-02 (Shared erp/v1 1.3.0, FinanceBaselineReference): what ERP needs so that other engines can REFER to an approved
-- Finance baseline version without ever holding its accounting configuration.
--
-- * A baseline's lineage id (baseline_id) and a version's digest are DERIVED from the approved row (provisioning.finance_baseline),
--   never stored, so there is nothing to backfill into the append-only baseline table and nothing that can drift from it.
-- * WITHDRAWN: Finance can withdraw its approval of a version. A withdrawal is its own append-only fact (who, why, evidence),
--   never an edit of the approved version, whose digest must stay stable.
-- * The provisioning command records the exact baseline references it was accepted under, so an audit can answer "which Finance
--   baseline caused this provisioning?".

CREATE TABLE baobab.financial_configuration_baseline_withdrawal (
    legal_entity_id    TEXT        NOT NULL,
    version            INTEGER     NOT NULL,
    withdrawn_by       TEXT        NOT NULL CHECK (
        btrim(withdrawn_by) <> '' AND withdrawn_by NOT LIKE 'REQUIRED\_%'
        AND lower(btrim(withdrawn_by)) NOT IN ('system', 'service', 'bootstrap', 'automation', 'auto', 'unknown', 'n/a', 'none')),
    withdrawn_at       TIMESTAMPTZ NOT NULL,
    reason             TEXT        NOT NULL CHECK (btrim(reason) <> ''),
    evidence_reference TEXT        NOT NULL CHECK (btrim(evidence_reference) <> '' AND evidence_reference NOT LIKE 'REQUIRED\_%'),
    recorded_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (legal_entity_id, version),
    FOREIGN KEY (legal_entity_id, version) REFERENCES baobab.financial_configuration_baseline (legal_entity_id, version)
);

CREATE FUNCTION baobab.financial_configuration_baseline_withdrawal_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'a baseline withdrawal is append-only: a withdrawal is never changed or undone, approve a new version instead'
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER financial_configuration_baseline_withdrawal_no_update_delete
    BEFORE UPDATE OR DELETE ON baobab.financial_configuration_baseline_withdrawal
    FOR EACH ROW EXECUTE FUNCTION baobab.financial_configuration_baseline_withdrawal_append_only();

ALTER TABLE baobab.erp_provisioning_command
    ADD COLUMN finance_baselines JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(finance_baselines) = 'array');
