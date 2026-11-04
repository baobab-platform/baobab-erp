-- ERP-owned recovery coordinate, not a CP grant or a canonical identity replacement.
-- Reserve before a remote JVM mutation so a lost result can recover the SAME
-- native UUID without shortening the original Trade order ID or POReference.
CREATE TABLE baobab.order_native_reference (
  tenant_id text NOT NULL,
  legal_entity_id text NOT NULL,
  commerce_order_id text NOT NULL CHECK (length(commerce_order_id) BETWEEN 3 AND 128),
  engine_instance_id text NOT NULL,
  ad_client_id integer NOT NULL CHECK (ad_client_id > 0),
  ad_org_id integer NOT NULL CHECK (ad_org_id > 0),
  order_version integer NOT NULL CHECK (order_version > 0),
  desired_digest text NOT NULL CHECK (desired_digest ~ '^sha256:[0-9a-f]{64}$'),
  first_source_event_id uuid NOT NULL,
  native_uuid uuid NOT NULL UNIQUE,
  creation_attempted_at timestamptz,
  native_id integer CHECK (native_id > 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id, legal_entity_id, commerce_order_id),
  UNIQUE (engine_instance_id, ad_client_id, ad_org_id, native_id),
  CHECK (native_id IS NULL OR creation_attempted_at IS NOT NULL)
);

CREATE FUNCTION baobab.order_native_reference_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'UPDATE' THEN
    RAISE EXCEPTION 'native order reference history cannot be removed';
  END IF;
  IF (to_jsonb(OLD) - 'creation_attempted_at' - 'native_id') IS DISTINCT FROM
     (to_jsonb(NEW) - 'creation_attempted_at' - 'native_id')
     OR (OLD.creation_attempted_at IS NOT NULL AND
         OLD.creation_attempted_at IS DISTINCT FROM NEW.creation_attempted_at)
     OR (OLD.native_id IS NOT NULL AND OLD.native_id IS DISTINCT FROM NEW.native_id) THEN
    RAISE EXCEPTION 'native order reference binding is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER order_native_reference_history BEFORE UPDATE OR DELETE
ON baobab.order_native_reference FOR EACH ROW
EXECUTE FUNCTION baobab.order_native_reference_history();
CREATE TRIGGER order_native_reference_no_truncate BEFORE TRUNCATE
ON baobab.order_native_reference FOR EACH STATEMENT
EXECUTE FUNCTION baobab.order_native_reference_history();
