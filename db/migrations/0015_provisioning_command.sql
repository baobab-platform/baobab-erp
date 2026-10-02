-- ERP-COMPAT: the durable provisioning COMMAND behind POST/GET /provisioning-operations (contracts/erp/v1).
--
-- One command may provision several legal entities. Each legal entity keeps its own ERP provisioning record in
-- baobab.erp_provisioning_operation (plan, steps, native mapping, status); the command groups them and owns the
-- idempotency scope and the contract-level state. Authority is stored as the exact Control Plane plan tuple the request
-- named, so what ERP accepted can always be traced to the approved plan it was compared with.

CREATE TABLE baobab.erp_provisioning_command (
    operation_id            UUID        PRIMARY KEY,
    tenant_id               TEXT        NOT NULL CHECK (btrim(tenant_id) <> ''),
    idempotency_key         TEXT        NOT NULL CHECK (length(idempotency_key) BETWEEN 16 AND 128),
    principal               TEXT        NOT NULL CHECK (btrim(principal) <> ''),
    request_fingerprint     TEXT        NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    tenant_provisioning_id  TEXT        NOT NULL,
    plan_id                 TEXT        NOT NULL,
    plan_version            INTEGER     NOT NULL CHECK (plan_version >= 1),
    plan_digest             TEXT        NOT NULL CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    legal_entity_ids        TEXT[]      NOT NULL CHECK (cardinality(legal_entity_ids) >= 1),
    state                   TEXT        NOT NULL DEFAULT 'accepted' CHECK (state IN
        ('accepted', 'validating', 'provisioning', 'reconciling', 'active', 'failed', 'cancelled')),
    revision                INTEGER     NOT NULL DEFAULT 1 CHECK (revision >= 1),
    failure_code            TEXT        CHECK (failure_code ~ '^[A-Z][A-Z0-9_]*$' AND length(failure_code) <= 96),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Shared idempotency policy scope: service, operation, tenant_id, idempotency_key.
    CONSTRAINT erp_provisioning_command_idempotency UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT erp_provisioning_command_failure_only_when_failed CHECK (failure_code IS NULL OR state = 'failed')
);

CREATE TABLE baobab.erp_provisioning_command_entity (
    operation_id    UUID NOT NULL REFERENCES baobab.erp_provisioning_command(operation_id),
    legal_entity_id TEXT NOT NULL,
    provisioning_id TEXT NOT NULL REFERENCES baobab.erp_provisioning_operation(provisioning_id),
    PRIMARY KEY (operation_id, legal_entity_id),
    UNIQUE (provisioning_id)
);
