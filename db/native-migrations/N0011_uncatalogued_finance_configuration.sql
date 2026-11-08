-- ERP native ADR-008/009/010/013/022: no hidden financial configuration path.
--
-- The iDempiere synchronous OSGi BEFORE hooks deny uncatalogued accounting
-- configuration operations in protected runtimes. A direct SQL statement,
-- migration-time workaround or rogue background actor can bypass Java hooks;
-- these tables therefore need an independent PostgreSQL guard for every
-- AD_Client that has EVER been placed under Baobab authority.
--
-- This does NOT mint an erp/v2 class for accounting configuration. Managed
-- chart/tax/bank configuration must be performed BEFORE a legal client is
-- placed, or after a separately reviewed Shared/CP-native governance change.
-- Historical placement closure does not create a backdoor. System client 0
-- release/configuration controls remain owned by the privileged deployment
-- process and must be independently qualified at the release gate.
--
-- Deliberately do not cover C_Period / C_PeriodControl here: closing and
-- reopening a financial period require an explicit, auditable lifecycle and
-- are a separate ERP-008/022 acceptance item.

CREATE FUNCTION baobab_native.forbid_uncatalogued_finance_configuration()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (TG_OP <> 'INSERT' AND baobab_native.client_is_placed(OLD.ad_client_id::integer))
     OR (TG_OP <> 'DELETE' AND baobab_native.client_is_placed(NEW.ad_client_id::integer)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: % accounting configuration has no governed operation class', TG_TABLE_NAME
      USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE
  config_table text;
BEGIN
  FOREACH config_table IN ARRAY ARRAY[
    'c_acctschema', 'c_elementvalue', 'c_validcombination',
    'c_tax', 'c_taxacct', 'c_bankaccount'
  ] LOOP
    IF to_regclass('adempiere.' || config_table) IS NULL THEN
      RAISE EXCEPTION 'N0011 requires real iDempiere accounting configuration table: %',
        config_table;
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_uncatalogued_finance_configuration
      BEFORE INSERT OR UPDATE OR DELETE ON adempiere.%I
      FOR EACH ROW EXECUTE FUNCTION baobab_native.forbid_uncatalogued_finance_configuration()',
      config_table);
  END LOOP;
END $$;
