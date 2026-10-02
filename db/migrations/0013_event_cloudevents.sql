-- ERP-COMPAT-05: store canonical CloudEvents 1.0 envelopes (Shared events/v1/envelope.schema.json).
--
-- * Legacy rows are history and are kept untouched except that undelivered ones are parked as 'held':
--   the legacy shape is archived by Shared as rejected, so it can no longer be delivered, and the
--   legacy producers have no registered canonical event to map to yet. Nothing is deleted.
-- * Canonical rows carry the envelope members in ce_* columns; the legacy-only columns become nullable
--   and a CHECK keeps each format internally complete.
-- * Inbox deduplication becomes (source, id) per contracts/idempotency/v1/policy.yaml, not id alone.

-- ---- outbox ----------------------------------------------------------------------------------
ALTER TABLE baobab.event_outbox
    ADD COLUMN envelope_format TEXT NOT NULL DEFAULT 'legacy'
        CONSTRAINT event_outbox_format_valid CHECK (envelope_format IN ('legacy', 'cloudevents')),
    ADD COLUMN ce_source TEXT,
    ADD COLUMN ce_subject TEXT,
    ADD COLUMN ce_dataschema TEXT,
    ADD COLUMN ce_scope TEXT,
    ADD COLUMN ce_correlation_id UUID,
    ADD COLUMN ce_causation_id UUID,
    ADD COLUMN ce_idempotency_key TEXT,
    ADD COLUMN ce_traceparent TEXT,
    ADD COLUMN ce_tracestate TEXT;

ALTER TABLE baobab.event_outbox
    ALTER COLUMN schema_version DROP NOT NULL,
    ALTER COLUMN tenant_id DROP NOT NULL,
    ALTER COLUMN entity_id DROP NOT NULL,
    ALTER COLUMN correlation_id DROP NOT NULL;

ALTER TABLE baobab.event_outbox DROP CONSTRAINT event_outbox_status_check;
ALTER TABLE baobab.event_outbox ADD CONSTRAINT event_outbox_status_check
    CHECK (status IN ('pending', 'retry', 'delivered', 'dead_letter', 'held'));

UPDATE baobab.event_outbox
   SET status = 'held',
       last_error = 'legacy envelope retired by ERP-COMPAT-05; no registered canonical event to deliver as'
 WHERE status IN ('pending', 'retry');

ALTER TABLE baobab.event_outbox ADD CONSTRAINT event_outbox_format_complete CHECK (
    (envelope_format = 'legacy' AND schema_version IS NOT NULL AND tenant_id IS NOT NULL
        AND entity_id IS NOT NULL AND correlation_id IS NOT NULL)
    OR
    (envelope_format = 'cloudevents' AND ce_source IS NOT NULL AND ce_subject IS NOT NULL
        AND ce_dataschema IS NOT NULL AND ce_correlation_id IS NOT NULL
        AND ce_scope IN ('platform', 'tenant')
        AND ((ce_scope = 'tenant' AND tenant_id IS NOT NULL) OR (ce_scope = 'platform' AND tenant_id IS NULL))
        AND event_type LIKE 'com.baobab-platform.%')
);

-- Only canonical rows are ever delivered.
DROP INDEX baobab.event_outbox_pending_idx;
CREATE INDEX event_outbox_pending_idx ON baobab.event_outbox (occurred_at)
    WHERE status IN ('pending', 'retry') AND envelope_format = 'cloudevents';

-- ---- inbox -----------------------------------------------------------------------------------
ALTER TABLE baobab.event_inbox
    ADD COLUMN envelope_format TEXT NOT NULL DEFAULT 'legacy'
        CONSTRAINT event_inbox_format_valid CHECK (envelope_format IN ('legacy', 'cloudevents')),
    ADD COLUMN ce_source TEXT,
    ADD COLUMN ce_subject TEXT,
    ADD COLUMN ce_dataschema TEXT,
    ADD COLUMN ce_scope TEXT,
    ADD COLUMN ce_correlation_id UUID,
    ADD COLUMN ce_causation_id UUID,
    ADD COLUMN ce_idempotency_key TEXT,
    ADD COLUMN ce_traceparent TEXT,
    ADD COLUMN ce_tracestate TEXT,
    ADD COLUMN ce_time TIMESTAMPTZ;

ALTER TABLE baobab.event_inbox
    ALTER COLUMN schema_version DROP NOT NULL,
    ALTER COLUMN source_engine DROP NOT NULL,
    ALTER COLUMN correlation_id DROP NOT NULL,
    ALTER COLUMN tenant_id DROP NOT NULL,
    ALTER COLUMN entity_id DROP NOT NULL;

ALTER TABLE baobab.event_inbox ADD CONSTRAINT event_inbox_format_complete CHECK (
    (envelope_format = 'legacy' AND schema_version IS NOT NULL AND source_engine IS NOT NULL
        AND correlation_id IS NOT NULL AND tenant_id IS NOT NULL AND entity_id IS NOT NULL)
    OR
    (envelope_format = 'cloudevents' AND ce_source IS NOT NULL AND ce_subject IS NOT NULL
        AND ce_dataschema IS NOT NULL AND ce_correlation_id IS NOT NULL AND ce_time IS NOT NULL
        AND ce_scope = 'tenant' AND tenant_id IS NOT NULL
        AND event_type LIKE 'com.baobab-platform.%')
);

-- (source, id) is the deduplication key for canonical events; a bare id stays unique for legacy history.
ALTER TABLE baobab.event_inbox DROP CONSTRAINT event_inbox_event_id_key;
CREATE UNIQUE INDEX event_inbox_legacy_event_id_unique
    ON baobab.event_inbox (event_id) WHERE envelope_format = 'legacy';
CREATE UNIQUE INDEX event_inbox_cloudevent_source_id_unique
    ON baobab.event_inbox (ce_source, event_id) WHERE envelope_format = 'cloudevents';
