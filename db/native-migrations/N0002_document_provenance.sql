-- P0-04B ERP (ADR-ERP-022): durable document-to-placement provenance.
--
-- The operating Organisation that performs an accounting operation is the one
-- established when the source document was CREATED, preserved through
-- completion and posting. It is recorded by the database itself for every
-- governed header table, so UI, REST, import, scheduler and direct SQL routes
-- all receive it. A placed AD_Client cannot create a governed document in an
-- AD_Org without a current placement: that would be unattributable.

CREATE TABLE baobab_native.document_provenance (
  native_table text NOT NULL CHECK (native_table ~ '^[A-Za-z_]{3,60}$'),
  record_id integer NOT NULL CHECK (record_id > 0),
  ad_client_id integer NOT NULL CHECK (ad_client_id > 0),
  ad_org_id integer NOT NULL CHECK (ad_org_id > 0),
  placement_id uuid NOT NULL,
  placement_version integer NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (native_table, record_id),
  FOREIGN KEY (placement_id, placement_version)
    REFERENCES baobab_native.native_placement (placement_id, version)
);

CREATE FUNCTION baobab_native.document_provenance_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'document provenance is immutable history' USING ERRCODE = '42501';
END $$;

CREATE TRIGGER document_provenance_immutable BEFORE UPDATE OR DELETE
  ON baobab_native.document_provenance FOR EACH ROW
  EXECUTE FUNCTION baobab_native.document_provenance_immutable();

-- The placement in force for a native org now, or NULL. Never more than one
-- (native_placement forbids overlap).
CREATE FUNCTION baobab_native.current_placement(p_client integer, p_org integer)
RETURNS baobab_native.native_placement LANGUAGE sql STABLE AS $$
  SELECT p.* FROM baobab_native.native_placement p
   WHERE p.ad_client_id = p_client AND p.ad_org_id = p_org
     AND p.effective_from <= clock_timestamp()
     AND (p.effective_to IS NULL OR p.effective_to > clock_timestamp())
$$;

CREATE FUNCTION baobab_native.client_is_placed(p_client integer)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM baobab_native.native_placement p WHERE p.ad_client_id = p_client)
$$;

-- AFTER INSERT on each governed header table: the new document inherits the
-- current placement of its native org, in the same transaction.
CREATE FUNCTION baobab_native.record_document_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE placement baobab_native.native_placement; record_id integer;
BEGIN
  IF NOT baobab_native.client_is_placed(NEW.ad_client_id) THEN
    RETURN NULL;
  END IF;
  placement := baobab_native.current_placement(NEW.ad_client_id, NEW.ad_org_id);
  IF placement.placement_id IS NULL THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: no current placement for AD_Client %/AD_Org %',
      NEW.ad_client_id, NEW.ad_org_id USING ERRCODE = '42501';
  END IF;
  record_id := (to_jsonb(NEW) ->> TG_ARGV[1])::integer;
  INSERT INTO baobab_native.document_provenance
    (native_table, record_id, ad_client_id, ad_org_id, placement_id, placement_version)
  VALUES (TG_ARGV[0], record_id, NEW.ad_client_id, NEW.ad_org_id, placement.placement_id, placement.version);
  RETURN NULL;
END $$;

-- An org change on an existing governed document would silently move it to a
-- different operating Organisation: forbidden for placed clients.
CREATE FUNCTION baobab_native.forbid_document_org_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.ad_client_id, NEW.ad_org_id) IS DISTINCT FROM (OLD.ad_client_id, OLD.ad_org_id)
     AND (baobab_native.client_is_placed(OLD.ad_client_id) OR baobab_native.client_is_placed(NEW.ad_client_id)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: a governed document cannot change client or organisation'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE doc record;
BEGIN
  IF to_regclass('adempiere.ad_client') IS NULL THEN
    RAISE EXCEPTION 'P0-04B ERP native migrations require the iDempiere adempiere schema';
  END IF;
  FOR doc IN SELECT * FROM (VALUES
      ('GL_Journal', 'gl_journal'), ('C_Invoice', 'c_invoice'), ('C_Payment', 'c_payment'),
      ('C_AllocationHdr', 'c_allocationhdr'), ('M_InOut', 'm_inout'), ('C_Order', 'c_order'),
      ('C_BankStatement', 'c_bankstatement'), ('C_Cash', 'c_cash')) AS t(native_table, relation)
  LOOP
    IF to_regclass('adempiere.' || doc.relation) IS NULL THEN
      RAISE EXCEPTION 'governed iDempiere table adempiere.% is missing', doc.relation;
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_document_provenance AFTER INSERT ON adempiere.%I
      FOR EACH ROW EXECUTE FUNCTION baobab_native.record_document_provenance(%L, %L)',
      doc.relation, doc.native_table, doc.relation || '_id');
    EXECUTE format('CREATE TRIGGER baobab_document_org_fixed BEFORE UPDATE OF ad_client_id, ad_org_id
      ON adempiere.%I FOR EACH ROW EXECUTE FUNCTION baobab_native.forbid_document_org_change()',
      doc.relation);
  END LOOP;
END $$;

REVOKE ALL ON baobab_native.document_provenance FROM PUBLIC;
