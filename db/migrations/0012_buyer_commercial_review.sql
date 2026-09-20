CREATE TABLE baobab.buyer_commercial_review (
    id BIGSERIAL PRIMARY KEY,
    review_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    buyer_organisation_id TEXT NOT NULL,
    canonical_organisation_id TEXT NOT NULL,
    business_partner_id TEXT NOT NULL,
    credit_status TEXT NOT NULL CHECK (credit_status IN ('APPROVED','ON_HOLD','REJECTED')),
    currency_code CHAR(3) NOT NULL,
    payment_term_code TEXT,
    credit_limit_minor BIGINT CHECK (credit_limit_minor IS NULL OR credit_limit_minor >= 0),
    profile_reference TEXT NOT NULL,
    decision_reference TEXT NOT NULL UNIQUE,
    decided_by_principal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    request_json JSONB NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX buyer_commercial_review_scope_idx
    ON baobab.buyer_commercial_review (tenant_id, legal_entity_id, buyer_organisation_id, decided_at DESC);
