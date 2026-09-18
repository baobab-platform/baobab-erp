CREATE TABLE IF NOT EXISTS baobab.erp_provisioning_native_mapping (
    provisioning_id text NOT NULL,
    resource_key text NOT NULL,
    native_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provisioning_id, resource_key),
    CONSTRAINT fk_erp_provisioning_native_mapping_operation
      FOREIGN KEY (provisioning_id)
      REFERENCES baobab.erp_provisioning_operation(provisioning_id)
      ON DELETE CASCADE
);
