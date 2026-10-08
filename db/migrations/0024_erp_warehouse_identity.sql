-- ERP-owned public identity for warehouses (ERP-CAP-08), following migration 0023's pattern for business partners.
--
-- A warehouse is identified outside ERP by a stable erp_ identifier minted at this boundary. It is independent of the approved
-- warehouse code (which can change), of the provisioning attempt that created the engine record, and of the iDempiere record
-- number (private to an engine instance, and replaceable on migration). The row binds the identity to its current approved code and
-- its current native record; GET /inventory-availability and warehouse.changed both speak the public id.
--
-- No platform canonical identity is invented: entity_mapping needs a canonical UUID and a warehouse has none.
CREATE TABLE baobab.erp_warehouse (
    erp_resource_id    TEXT        PRIMARY KEY DEFAULT 'erp_' || replace(gen_random_uuid()::text, '-', ''),
    tenant_id          TEXT        NOT NULL,
    legal_entity_id    TEXT        NOT NULL,
    code               TEXT,
    name               TEXT,
    country            TEXT,
    timezone           TEXT,
    status             TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    engine_instance_id TEXT,
    native_id          BIGINT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT erp_warehouse_public_id_format CHECK (erp_resource_id ~ '^erp_[a-z0-9]{4,59}$')
);
-- One identity per approved code within a legal entity, and one per native record within an engine instance.
CREATE UNIQUE INDEX erp_warehouse_code_unique ON baobab.erp_warehouse (tenant_id, legal_entity_id, code) WHERE code IS NOT NULL;
CREATE UNIQUE INDEX erp_warehouse_native_unique ON baobab.erp_warehouse (engine_instance_id, native_id) WHERE native_id IS NOT NULL;

-- Warehouses that GET /inventory-availability could already resolve (hand-written entity_mapping rows) keep their public id. They are
-- carried over here and retired there, so a warehouse never has two competing active identities.
INSERT INTO baobab.erp_warehouse (erp_resource_id, tenant_id, legal_entity_id, engine_instance_id, native_id)
SELECT em.erp_resource_id, em.tenant_id, em.legal_entity_id, tm.engine_instance_id, em.native_id
  FROM baobab.entity_mapping em
  LEFT JOIN baobab.tenant_mapping tm
         ON tm.tenant_id = em.tenant_id AND tm.entity_id = em.legal_entity_id AND tm.status = 'active'
 WHERE em.native_table = 'M_Warehouse' AND em.status = 'active' AND em.legal_entity_id IS NOT NULL
   AND (em.effective_to IS NULL OR em.effective_to > now())
ON CONFLICT DO NOTHING;

UPDATE baobab.entity_mapping
   SET status = 'retired', effective_to = COALESCE(effective_to, GREATEST(now(), effective_from + interval '1 microsecond'))
 WHERE native_table = 'M_Warehouse' AND status = 'active' AND legal_entity_id IS NOT NULL
   AND erp_resource_id IN (SELECT erp_resource_id FROM baobab.erp_warehouse);

-- Warehouses the provisioning executor created before identities existed. Their operations are already ready, so the executor's own
-- registration pass never revisits them: they are carried over here from the native mapping and the approved desired state (never by
-- name; the code is the one the step was approved with, the country is its market's). They have no declared timezone, so they are
-- registered but not announced. The most recent operation wins where one code was provisioned more than once; rows already carried
-- over from entity_mapping above keep their public id.
INSERT INTO baobab.erp_warehouse (tenant_id, legal_entity_id, code, name, country, engine_instance_id, native_id)
SELECT op.desired_state->>'tenant_id', op.desired_state->>'legal_entity_id', k.code, k.code, market->>'country_code',
       op.desired_state->>'engine_instance_id', nm.native_id
  FROM baobab.erp_provisioning_native_mapping nm
  JOIN baobab.erp_provisioning_operation op ON op.provisioning_id = nm.provisioning_id
 CROSS JOIN LATERAL (SELECT substring(nm.resource_key from ':warehouse:([^:]+):') AS market_id,
                            substring(nm.resource_key from ':warehouse:[^:]+:(.+)$') AS code) k
  JOIN LATERAL jsonb_array_elements(op.desired_state->'markets') AS market ON market->>'market_id' = k.market_id
 WHERE nm.resource_key LIKE 'create_warehouse:%:warehouse:%' AND nm.native_id > 1 AND op.status IN ('ready', 'active')
   AND op.desired_state->>'tenant_id' IS NOT NULL AND op.desired_state->>'legal_entity_id' IS NOT NULL
 ORDER BY op.created_at DESC
ON CONFLICT DO NOTHING;
