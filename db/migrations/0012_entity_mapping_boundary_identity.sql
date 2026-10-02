-- ERP-COMPAT-02: bring baobab.entity_mapping to contracts/erp/v1/mapping.schema.json
-- (Shared 739f0ca) without making ERP an authority for legal-entity identity
-- (ADR-BCP-018 section 95: canonical Legal Entity -> explicit ERP mapping, never the reverse).
--
-- * mapping_id / erp_resource_id: public identifiers minted by this boundary, never an
--   iDempiere id. Existing rows are backfilled deterministically from the primary key.
-- * status: the five contract values. 'superseded' was the only retired state and maps to
--   'retired'.
-- * canonical_owner: with canonical_type and canonical_id this forms the contract's
--   canonical_reference. Legacy rows have no recorded owner and stay NULL until reconciled.
-- * legacy rows without a legal_entity_id are NOT assigned one (a tenant may have several
--   legal entities, and a default can have changed). Active ones are quarantined for a
--   separate reconciliation against Control Plane mappings.

ALTER TABLE baobab.entity_mapping
    ADD COLUMN mapping_id TEXT,
    ADD COLUMN erp_resource_id TEXT,
    ADD COLUMN canonical_owner TEXT,
    ADD COLUMN quarantine_reason TEXT;

UPDATE baobab.entity_mapping
   SET mapping_id = 'map_' || lpad(to_hex(id), 12, '0'),
       erp_resource_id = 'erp_' || lpad(to_hex(id), 12, '0');

ALTER TABLE baobab.entity_mapping
    ALTER COLUMN mapping_id SET NOT NULL,
    ALTER COLUMN mapping_id SET DEFAULT 'map_' || replace(gen_random_uuid()::text, '-', ''),
    ALTER COLUMN erp_resource_id SET NOT NULL,
    ALTER COLUMN erp_resource_id SET DEFAULT 'erp_' || replace(gen_random_uuid()::text, '-', ''),
    ADD CONSTRAINT entity_mapping_mapping_id_unique UNIQUE (mapping_id),
    ADD CONSTRAINT entity_mapping_erp_resource_id_unique UNIQUE (erp_resource_id),
    ADD CONSTRAINT entity_mapping_mapping_id_format CHECK (mapping_id ~ '^map_[a-z0-9]{4,59}$'),
    ADD CONSTRAINT entity_mapping_erp_resource_id_format CHECK (erp_resource_id ~ '^erp_[a-z0-9]{4,59}$'),
    ADD CONSTRAINT entity_mapping_canonical_owner_valid CHECK (
        canonical_owner IS NULL OR canonical_owner IN
            ('control-plane', 'shared', 'trade', 'erp', 'identity-provider', 'payment-provider'));

-- The partial unique indexes below are keyed on status = 'active', so the status check can
-- be replaced without touching them.
ALTER TABLE baobab.entity_mapping DROP CONSTRAINT IF EXISTS entity_mapping_status_check;
UPDATE baobab.entity_mapping SET status = 'retired' WHERE status = 'superseded';
ALTER TABLE baobab.entity_mapping
    ADD CONSTRAINT entity_mapping_status_check
    CHECK (status IN ('pending', 'active', 'suspended', 'retired', 'quarantined'));

UPDATE baobab.entity_mapping
   SET status = 'quarantined',
       quarantine_reason = 'legacy mapping has no legal_entity_id; reconcile against Control Plane'
 WHERE legal_entity_id IS NULL AND status = 'active';

-- Only a mapping that is not live may lack a legal entity.
ALTER TABLE baobab.entity_mapping
    ADD CONSTRAINT entity_mapping_live_requires_legal_entity
    CHECK (legal_entity_id IS NOT NULL OR status IN ('pending', 'retired', 'quarantined')),
    ADD CONSTRAINT entity_mapping_quarantine_reason_present
    CHECK (status <> 'quarantined' OR quarantine_reason IS NOT NULL);

-- Contract identifier grammars (control-plane/v1/domain.schema.json). NOT VALID: enforced for
-- every new or changed row; legacy rows are reported by the quarantine reconciliation, not
-- rewritten here.
ALTER TABLE baobab.entity_mapping
    ADD CONSTRAINT entity_mapping_tenant_id_format
        CHECK (tenant_id ~ '^tn_[a-z0-9]{3,60}$') NOT VALID,
    ADD CONSTRAINT entity_mapping_legal_entity_id_format
        CHECK (legal_entity_id IS NULL
               OR (legal_entity_id ~ '^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$' AND length(legal_entity_id) BETWEEN 3 AND 63)) NOT VALID;

CREATE INDEX entity_mapping_quarantined_idx
    ON baobab.entity_mapping (tenant_id, canonical_type)
    WHERE status = 'quarantined';
