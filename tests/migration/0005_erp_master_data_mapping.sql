CREATE TABLE IF NOT EXISTS baobab.erp_master_data_mapping (
  engine_instance_id text NOT NULL,
  legal_entity_id text NOT NULL,
  resource_kind text NOT NULL,
  canonical_id text NOT NULL,
  native_id bigint NOT NULL,
  desired_digest text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (engine_instance_id, legal_entity_id, resource_kind, canonical_id)
);
CREATE INDEX IF NOT EXISTS idx_erp_master_data_native
ON baobab.erp_master_data_mapping(engine_instance_id, legal_entity_id, resource_kind, native_id);
