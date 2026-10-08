-- Execution bookkeeping for accepted provisioning operations (application/provisioning_worker.py, ADR-ERP-019).
-- An operation is claimed by taking a session advisory lock on its id (a dead worker's lock disappears with its connection), so
-- there is no lease to expire. These columns only schedule the next pass and say why the last one ended.
ALTER TABLE baobab.erp_provisioning_operation
    ADD COLUMN IF NOT EXISTS attempts        integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz,
    ADD COLUMN IF NOT EXISTS outcome_code    text;

CREATE INDEX IF NOT EXISTS erp_provisioning_due_idx
    ON baobab.erp_provisioning_operation (next_attempt_at, created_at)
    WHERE status IN ('planned', 'applying', 'reconciling');
