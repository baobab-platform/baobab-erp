-- ADR-ERP-003 / ADR-ERP-021: an effective legal-entity isolation boundary
-- cannot be merely a different AD_Org inside the same native AD_Client.
-- AD_Client_ID is scoped by EngineInstance; never confuse a numeric native ID
-- with a canonical legal entity or platform Tenant.
--
-- Forward only: do not edit previous migrations or silently move existing
-- companies. If historical active placements share this Client in one
-- EngineInstance, this migration FAILS and requires an independently reviewed
-- legal-entity migration/repair under the native placement policy.
-- Legacy rows with no EngineInstance are not made authoritative by this index;
-- they remain non-routable to the governed native ERP consumers.
CREATE UNIQUE INDEX tenant_mapping_instance_client_active_unique
    ON baobab.tenant_mapping (engine_instance_id, ad_client_id)
    WHERE status = 'active'
      AND engine_instance_id IS NOT NULL
      AND ad_client_id > 0;
