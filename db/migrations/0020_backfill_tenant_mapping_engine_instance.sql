-- PERSIST_MAPPING used to write baobab.tenant_mapping without engine_instance_id, so a provisioned legal entity resolved a
-- context but nothing keyed by its EngineInstance (master-data mappings, inventory reads, order execution). New rows now carry it.
-- This fills in the rows written before, from the one authoritative record of where each was provisioned: the provisioning
-- operation's own desired state (tenant, legal entity, engine_instance_id).
--
-- Only an unambiguous answer is applied: a tenant mapping is filled when every non-failed provisioning operation for its
-- (tenant, legal entity) names the same, non-blank EngineInstance. An operation that names none counts against agreement
-- (there is no evidence it used the same instance). Rows with no operation, or with operations that disagree or are
-- incomplete, stay NULL (and keep failing closed as unmapped) for an operator to resolve; nothing is guessed. Rows that
-- already have a value are never changed.
UPDATE baobab.tenant_mapping AS mapping
   SET engine_instance_id = source.engine_instance_id, updated_at = now()
  FROM (
        SELECT desired_state ->> 'tenant_id'          AS tenant_id,
               desired_state ->> 'legal_entity_id'    AS legal_entity_id,
               min(desired_state ->> 'engine_instance_id') AS engine_instance_id
          FROM baobab.erp_provisioning_operation
         WHERE status IN ('applying', 'reconciling', 'ready', 'active')
         GROUP BY 1, 2
        HAVING bool_and(coalesce(desired_state ->> 'engine_instance_id', '') <> '')
           AND count(DISTINCT desired_state ->> 'engine_instance_id') = 1
       ) AS source
 WHERE mapping.engine_instance_id IS NULL
   AND mapping.status = 'active'
   AND mapping.tenant_id = source.tenant_id
   AND mapping.entity_id = source.legal_entity_id;
