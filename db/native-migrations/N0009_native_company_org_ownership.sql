-- DEV-09: forward-only ownership validation for native placement.
-- This deliberately does not edit the already-applied N0001 checksum/history.
-- iDempiere AD_Org is owned by AD_Client, independent of CP metadata.
-- Operator-provided tenant, Organisation or legal entity cannot move a native
-- org between native companies.
DO $$
BEGIN
  IF to_regclass('adempiere.ad_org') IS NULL THEN
    RAISE EXCEPTION 'DEV-09 requires the native iDempiere AD_Org catalogue';
  END IF;
  -- Fail the upgrade if an existing OPEN placement contradicts native state.
  -- Never auto-repair a legal-actor or company mapping.
  IF EXISTS (
    SELECT 1 FROM baobab_native.native_placement p
    LEFT JOIN adempiere.ad_org o ON o.ad_org_id = p.ad_org_id
    WHERE p.effective_to IS NULL AND (
      o.ad_org_id IS NULL OR o.ad_client_id <> p.ad_client_id OR o.isactive <> 'Y'
    )
  ) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: open placements contradict native AD_Org ownership';
  END IF;
END $$;

CREATE FUNCTION baobab_native.native_placement_org_owner_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM adempiere.ad_org o
     WHERE o.ad_org_id = NEW.ad_org_id
       AND o.ad_client_id = NEW.ad_client_id
       AND o.isactive = 'Y'
  ) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: AD_Org is absent, inactive or belongs to another AD_Client'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;

-- N0001 remains the append-only / overlapping-placement authority. This
-- independent insert guard narrows allowed new placements, never grants them.
CREATE TRIGGER native_placement_org_owner_guard
  BEFORE INSERT ON baobab_native.native_placement
  FOR EACH ROW EXECUTE FUNCTION baobab_native.native_placement_org_owner_guard();
