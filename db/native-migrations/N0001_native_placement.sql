-- P0-04B ERP (ADR-SHARED-034, ADR-ERP-022): ERP-owned native placement.
--
-- Records WHERE ERP placed a Control Plane operating Organisation: which
-- iDempiere AD_Client/AD_Org represents (tenant, operating Organisation,
-- responsible legal entity, market) on one engine instance. A placement NEVER
-- creates authority: every posting still needs a current CP posting-authority
-- decision for the same Organisation and legal entity.
--
-- The association is a deliberate, evidenced maker/checker decision. It is
-- never inferred from AD_Org names, a tenant default or group ownership.
-- Append-only and versioned: the only permitted change is closing the open
-- window of a version, once, never into the past.
CREATE SCHEMA IF NOT EXISTS baobab_native;

CREATE TABLE baobab_native.native_placement (
  placement_id uuid NOT NULL,
  version integer NOT NULL CHECK (version >= 1),
  tenant_id text NOT NULL CHECK (tenant_id ~ '^tn_[a-z0-9]+$' AND length(tenant_id) BETWEEN 6 AND 63),
  engine_instance_id text NOT NULL CHECK (engine_instance_id ~ '^ei_[a-z0-9]+$' AND length(engine_instance_id) BETWEEN 6 AND 63),
  operating_organisation_id uuid NOT NULL,
  legal_entity_id text NOT NULL CHECK (legal_entity_id ~ '^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$' AND length(legal_entity_id) BETWEEN 3 AND 63),
  market char(2) NOT NULL CHECK (market ~ '^[A-Z]{2}$'),
  ad_client_id integer NOT NULL CHECK (ad_client_id > 0),
  ad_org_id integer NOT NULL CHECK (ad_org_id > 0),
  effective_from timestamptz NOT NULL,
  effective_to timestamptz,
  approved_by text NOT NULL CHECK (
    btrim(approved_by) <> '' AND approved_by NOT LIKE 'REQUIRED\_%'
    AND lower(btrim(approved_by)) NOT IN ('system', 'service', 'bootstrap', 'automation', 'auto', 'unknown', 'n/a', 'none')),
  checked_by text NOT NULL CHECK (
    btrim(checked_by) <> '' AND checked_by NOT LIKE 'REQUIRED\_%'
    AND lower(btrim(checked_by)) NOT IN ('system', 'service', 'bootstrap', 'automation', 'auto', 'unknown', 'n/a', 'none')),
  evidence_reference text NOT NULL CHECK (btrim(evidence_reference) <> '' AND evidence_reference NOT LIKE 'REQUIRED\_%'),
  erp_assignment_reference text NOT NULL CHECK (btrim(erp_assignment_reference) <> ''),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (placement_id, version),
  CHECK (lower(btrim(approved_by)) <> lower(btrim(checked_by))),
  CHECK (effective_to IS NULL OR effective_to > effective_from)
);

-- At most one open version per native client/organisation.
CREATE UNIQUE INDEX native_placement_one_open_per_org
  ON baobab_native.native_placement (ad_client_id, ad_org_id) WHERE effective_to IS NULL;
CREATE INDEX native_placement_client_idx
  ON baobab_native.native_placement (ad_client_id, ad_org_id, effective_from DESC);

CREATE FUNCTION baobab_native.native_placement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'native placement history cannot be deleted' USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    -- Only closing an open window, once, at or after now.
    IF (to_jsonb(NEW) - 'effective_to') IS DISTINCT FROM (to_jsonb(OLD) - 'effective_to')
       OR OLD.effective_to IS NOT NULL OR NEW.effective_to IS NULL
       OR NEW.effective_to < clock_timestamp() - interval '1 second' THEN
      RAISE EXCEPTION 'native placement is append-only; only an open window may be closed, never backdated'
        USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('native-placement/' || NEW.ad_client_id || '/' || NEW.ad_org_id, 0));
  -- Versions of one placement are consecutive and keep their CP identity;
  -- a different Organisation, legal entity or tenant is a new placement.
  IF NEW.version > 1 AND NOT EXISTS (
       SELECT 1 FROM baobab_native.native_placement p
        WHERE p.placement_id = NEW.placement_id AND p.version = NEW.version - 1) THEN
    RAISE EXCEPTION 'placement versions must be consecutive' USING ERRCODE = '23514';
  END IF;
  IF EXISTS (SELECT 1 FROM baobab_native.native_placement p
              WHERE p.placement_id = NEW.placement_id
                AND (p.tenant_id, p.operating_organisation_id, p.legal_entity_id, p.ad_client_id, p.ad_org_id)
                    IS DISTINCT FROM
                    (NEW.tenant_id, NEW.operating_organisation_id, NEW.legal_entity_id, NEW.ad_client_id, NEW.ad_org_id)) THEN
    RAISE EXCEPTION 'a placement version cannot change its tenant, Organisation, legal entity or native org'
      USING ERRCODE = '23514';
  END IF;
  -- Windows for one native org never overlap: ambiguity must be impossible.
  IF EXISTS (SELECT 1 FROM baobab_native.native_placement p
              WHERE p.ad_client_id = NEW.ad_client_id AND p.ad_org_id = NEW.ad_org_id
                AND tstzrange(p.effective_from, p.effective_to, '[)')
                    && tstzrange(NEW.effective_from, NEW.effective_to, '[)')) THEN
    RAISE EXCEPTION 'overlapping native placement for AD_Client %/AD_Org %', NEW.ad_client_id, NEW.ad_org_id
      USING ERRCODE = '23P01';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER native_placement_guard BEFORE INSERT OR UPDATE OR DELETE
  ON baobab_native.native_placement FOR EACH ROW EXECUTE FUNCTION baobab_native.native_placement_guard();

REVOKE ALL ON baobab_native.native_placement FROM PUBLIC;
