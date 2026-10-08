-- ERP-owned public identity for master data (ERP-CAP-08). A business partner or warehouse that ERP publishes is identified outside ERP
-- by a stable erp_ identifier minted at this boundary; the Trade customer id stays the canonical source reference and the iDempiere
-- record id stays private to the engine instance. The id is minted once, when the mapping is first written, and survives updates,
-- retries and restarts (the upsert never touches it). Existing mappings are backfilled by their own row, never by name or code.
ALTER TABLE baobab.erp_master_data_mapping ADD COLUMN erp_resource_id TEXT;
UPDATE baobab.erp_master_data_mapping SET erp_resource_id = 'erp_' || replace(gen_random_uuid()::text, '-', '')
 WHERE erp_resource_id IS NULL;
ALTER TABLE baobab.erp_master_data_mapping
    ALTER COLUMN erp_resource_id SET NOT NULL,
    ALTER COLUMN erp_resource_id SET DEFAULT 'erp_' || replace(gen_random_uuid()::text, '-', ''),
    ADD CONSTRAINT erp_master_data_mapping_public_id_unique UNIQUE (erp_resource_id),
    ADD CONSTRAINT erp_master_data_mapping_public_id_format CHECK (erp_resource_id ~ '^erp_[a-z0-9]{4,59}$');

-- Revisions of published master data share the table that tracks accounting outcomes.
ALTER TABLE baobab.document_outcome DROP CONSTRAINT document_outcome_document_type_check;
ALTER TABLE baobab.document_outcome ADD CONSTRAINT document_outcome_document_type_check
    CHECK (document_type IN ('invoice', 'payment', 'business_partner', 'warehouse'));
