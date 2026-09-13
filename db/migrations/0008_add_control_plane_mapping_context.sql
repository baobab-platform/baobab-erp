-- Bridge ERP mappings to the canonical Control Plane context without conflating
-- tenant, legal entity, EngineInstance or capability binding (ADR-ERP-002/007/019).
ALTER TABLE baobab.tenant_mapping
    ADD COLUMN legal_entity_id TEXT,
    ADD COLUMN engine_instance_id TEXT,
    ADD COLUMN capability_binding_id TEXT,
    ADD COLUMN effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN effective_to TIMESTAMPTZ;

ALTER TABLE baobab.tenant_mapping
    ADD CONSTRAINT tenant_mapping_effective_period_valid
    CHECK (effective_to IS NULL OR effective_to > effective_from);

CREATE UNIQUE INDEX tenant_mapping_active_legal_entity_unique
    ON baobab.tenant_mapping (tenant_id, legal_entity_id, ad_org_id)
    WHERE status = 'active' AND legal_entity_id IS NOT NULL;

ALTER TABLE baobab.entity_mapping
    ADD COLUMN legal_entity_id TEXT,
    ADD COLUMN revision INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN effective_to TIMESTAMPTZ,
    ADD COLUMN replaces_mapping_id BIGINT REFERENCES baobab.entity_mapping(id);

ALTER TABLE baobab.entity_mapping
    ADD CONSTRAINT entity_mapping_revision_positive CHECK (revision > 0),
    ADD CONSTRAINT entity_mapping_effective_period_valid
        CHECK (effective_to IS NULL OR effective_to > effective_from);

CREATE INDEX entity_mapping_legal_entity_idx
    ON baobab.entity_mapping (tenant_id, legal_entity_id, canonical_type)
    WHERE legal_entity_id IS NOT NULL;
