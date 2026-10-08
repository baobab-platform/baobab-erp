-- Durable execution state for received canonical events (ADR-ERP-006, ADR-ERP-016).
--
-- The inbox so far only recorded receipt. A worker now claims received rows and executes them, so a row needs a lease
-- (claimed_by, lease_expires_at: a crashed worker's claim expires and the row is re-claimed), an attempt budget
-- (attempts, next_attempt_at) and an outcome (outcome_code, last_error). 'received' rows already present are claimable.
--   received    accepted at ingress, not yet claimed
--   processing  claimed; lease_expires_at bounds how long
--   retry       a transient failure; next_attempt_at holds the backoff
--   blocked     a precondition is missing (a mapping, a tenant, engine credentials); retried slowly, never fabricated
--   processed   executed, or recognised as already executed
--   dead_letter stopped; for an operator ('failed' is the pre-worker label and is kept valid)
ALTER TABLE baobab.event_inbox DROP CONSTRAINT event_inbox_status_check;
ALTER TABLE baobab.event_inbox ADD CONSTRAINT event_inbox_status_check
    CHECK (status IN ('received', 'processing', 'retry', 'blocked', 'processed', 'failed', 'dead_letter'));
ALTER TABLE baobab.event_inbox
    ADD COLUMN attempts         INTEGER     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    ADD COLUMN next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN claimed_by       TEXT,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN outcome_code     TEXT CHECK (outcome_code IS NULL OR outcome_code ~ '^[A-Z][A-Z0-9_]*$');

CREATE INDEX event_inbox_claimable_idx ON baobab.event_inbox (next_attempt_at, id)
    WHERE envelope_format = 'cloudevents' AND status IN ('received', 'retry', 'blocked', 'processing');

-- The native sales order ERP holds for a Trade order. Trade identifiers are opaque strings (order_01k...), so this is not
-- baobab.entity_mapping, whose canonical_id is a UUID. One row per (tenant, Trade order): the guard that a replay, a
-- second event for the same order or a second worker can never create a second sales order. It is written in the same
-- transaction as the consequence record and the event announcing it. 'adopted' marks a native order found by its
-- reference after an earlier attempt whose outcome was uncertain (created, then the worker died before this commit).
CREATE TABLE baobab.order_execution (
    tenant_id          TEXT        NOT NULL,
    commerce_order_id  TEXT        NOT NULL,
    legal_entity_id    TEXT        NOT NULL,
    order_version      INTEGER     NOT NULL CHECK (order_version >= 1),
    erp_order_id       TEXT        NOT NULL CHECK (erp_order_id ~ '^erp_[a-z0-9]{4,59}$'),
    native_table       TEXT        NOT NULL DEFAULT 'C_Order' CHECK (native_table = 'C_Order'),
    native_id          BIGINT      NOT NULL,
    source_event_id    UUID        NOT NULL,
    adopted            BOOLEAN     NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, commerce_order_id),
    CONSTRAINT order_execution_erp_order_id_unique UNIQUE (erp_order_id),
    CONSTRAINT order_execution_native_unique UNIQUE (tenant_id, native_table, native_id),
    FOREIGN KEY (tenant_id, commerce_order_id) REFERENCES baobab.order_consequence (tenant_id, commerce_order_id)
);
