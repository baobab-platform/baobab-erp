CREATE TABLE baobab.erp_provisioning_operation (
    provisioning_id       TEXT PRIMARY KEY,
    idempotency_key       TEXT NOT NULL UNIQUE,
    desired_state         JSONB NOT NULL,
    desired_state_digest  TEXT,
    plan                  JSONB,
    status                TEXT NOT NULL CHECK (status IN
        ('requested','validating','planned','applying','reconciling','ready','active','failed','suspended')),
    last_error             TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE baobab.erp_provisioning_step (
    provisioning_id TEXT NOT NULL REFERENCES baobab.erp_provisioning_operation(provisioning_id),
    step_key         TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('pending','running','completed','failed')),
    result           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provisioning_id, step_key)
);

CREATE INDEX erp_provisioning_status_idx ON baobab.erp_provisioning_operation(status, updated_at);
