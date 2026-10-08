-- The revision a document's accounting outcome has reached (ERP-CAP-05): one row per invoice or payment, advanced only when what ERP
-- observed changed, so each change is announced once (invoice.changed, payment.accounting-changed) however often a request is retried.
-- Written in the same transaction as the outbox row that announces the revision.
CREATE TABLE baobab.document_outcome (
    tenant_id      TEXT        NOT NULL,
    document_type  TEXT        NOT NULL CHECK (document_type IN ('invoice', 'payment')),
    document_id    TEXT        NOT NULL,
    revision       INTEGER     NOT NULL CHECK (revision >= 1),
    status         TEXT        NOT NULL,
    detail         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at  TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, document_type, document_id)
);
