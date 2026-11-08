-- ERP native ADR-002/007/008/017/019/022: historic iDempiere company
-- and organisation IDs remain bound to their original legal-actor records.
--
-- N0009 forbids moving/deleting an AD_Org while it has an OPEN placement.
-- After closure, reassignment or deletion would otherwise make immutable
-- provenance and historical ledger IDs misleading. Closing a placement is
-- deactivation, NOT permission to recycle a native identity.
--
-- Do not block a separately governed deactivation once all placements are
-- closed; do block identity recycling, deletion and in-place rewriting
-- irrespective of whether the placement has expired.

CREATE OR REPLACE FUNCTION baobab_native.placed_ad_org_change_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM baobab_native.native_placement p
               WHERE p.ad_org_id = OLD.ad_org_id
                 AND p.ad_client_id = OLD.ad_client_id) THEN
      RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: historical placed AD_Org cannot be deleted'
        USING ERRCODE = '42501';
    END IF;
    RETURN OLD;
  END IF;
  IF (NEW.ad_client_id, NEW.ad_org_id)
       IS DISTINCT FROM (OLD.ad_client_id, OLD.ad_org_id)
     AND EXISTS (SELECT 1 FROM baobab_native.native_placement p
                  WHERE p.ad_org_id = OLD.ad_org_id
                    AND p.ad_client_id = OLD.ad_client_id) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: historical AD_Org ID or company cannot be reassigned'
      USING ERRCODE = '42501';
  END IF;
  IF NEW.isactive IS DISTINCT FROM OLD.isactive
     AND EXISTS (SELECT 1 FROM baobab_native.native_placement p
                  WHERE p.ad_org_id = OLD.ad_org_id
                    AND p.ad_client_id = OLD.ad_client_id
                    AND p.effective_to IS NULL) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: close native placement before deactivating AD_Org'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION baobab_native.placed_ad_client_change_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM baobab_native.native_placement p
               WHERE p.ad_client_id = OLD.ad_client_id) THEN
      RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: historical placed AD_Client cannot be deleted'
        USING ERRCODE = '42501';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.ad_client_id IS DISTINCT FROM OLD.ad_client_id
     AND EXISTS (SELECT 1 FROM baobab_native.native_placement p
                  WHERE p.ad_client_id = OLD.ad_client_id) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: historical AD_Client ID cannot be reassigned'
      USING ERRCODE = '42501';
  END IF;
  IF NEW.isactive IS DISTINCT FROM OLD.isactive
     AND EXISTS (SELECT 1 FROM baobab_native.native_placement p
                  WHERE p.ad_client_id = OLD.ad_client_id
                    AND p.effective_to IS NULL) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: close all native placements before deactivating AD_Client'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

-- N0009 already registered the org guard on company/status updates.
-- Keep it in place; add a separate key-update path because PostgreSQL
-- UPDATE OF trigger columns do not include AD_Org_ID in that old trigger.
CREATE TRIGGER baobab_placed_ad_org_key_history_guard
  BEFORE UPDATE OF ad_org_id ON adempiere.ad_org
  FOR EACH ROW EXECUTE FUNCTION baobab_native.placed_ad_org_change_guard();

CREATE TRIGGER baobab_placed_ad_client_history_guard
  BEFORE UPDATE OF ad_client_id, isactive OR DELETE ON adempiere.ad_client
  FOR EACH ROW EXECUTE FUNCTION baobab_native.placed_ad_client_change_guard();
