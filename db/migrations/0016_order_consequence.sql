-- ERP-owned order-consequence read model (ADR-ERP-016; contracts/erp/v1/order-consequence-status.schema.json).
--
-- One row per Trade order the ERP is processing. It records the facts ERP itself observed (each native process it ran
-- successfully) and the consequence status ERP derived from them. It is never a mirror of a native DocStatus. The three
-- *_at columns are the observed facts; the status columns are derived from them by modules/order_to_cash/consequence.py
-- and stored so the read is a plain lookup. Written in the same transaction as the mapping and outbox rows it relates to.
CREATE TABLE baobab.order_consequence (
    tenant_id            TEXT        NOT NULL,
    commerce_order_id    TEXT        NOT NULL,
    legal_entity_id      TEXT        NOT NULL,
    order_version        INTEGER     NOT NULL CHECK (order_version >= 1),
    erp_order_id         TEXT        NOT NULL CHECK (erp_order_id ~ '^erp_[a-z0-9]{4,59}$'),
    status               TEXT        NOT NULL
        CHECK (status IN ('accepted', 'processing', 'posted', 'needs_review', 'rejected', 'compensated')),
    accounting_status    TEXT        NOT NULL
        CHECK (accounting_status IN ('not_applicable', 'pending', 'posted', 'needs_review', 'failed')),
    inventory_status     TEXT        NOT NULL
        CHECK (inventory_status IN ('not_applicable', 'pending', 'allocated', 'backordered', 'fulfilled',
                                    'needs_review', 'failed')),
    invoice_id           TEXT        CHECK (invoice_id IS NULL OR invoice_id ~ '^erp_[a-z0-9]{4,59}$'),
    exception_code       TEXT        CHECK (exception_code IS NULL
                                            OR (exception_code ~ '^[A-Z][A-Z0-9_]*$' AND length(exception_code) <= 96)),
    order_completed_at   TIMESTAMPTZ,
    shipment_completed_at TIMESTAMPTZ,
    invoice_posted_at    TIMESTAMPTZ,
    revision             INTEGER     NOT NULL DEFAULT 1 CHECK (revision >= 1),
    updated_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, commerce_order_id),
    CONSTRAINT order_consequence_erp_order_id_unique UNIQUE (erp_order_id),
    CONSTRAINT order_consequence_exception_for_problem CHECK (
        exception_code IS NOT NULL
        OR (status NOT IN ('needs_review', 'rejected', 'compensated')
            AND accounting_status NOT IN ('needs_review', 'failed')
            AND inventory_status NOT IN ('needs_review', 'failed'))
    )
);

-- The shipment and invoice documents ERP created for an order, so completing one updates the right order.
CREATE TABLE baobab.order_consequence_document (
    tenant_id          TEXT NOT NULL,
    document_type      TEXT NOT NULL CHECK (document_type IN ('GoodsShipment', 'CustomerInvoice')),
    document_id        TEXT NOT NULL,
    commerce_order_id  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, document_type, document_id),
    FOREIGN KEY (tenant_id, commerce_order_id) REFERENCES baobab.order_consequence (tenant_id, commerce_order_id)
);
