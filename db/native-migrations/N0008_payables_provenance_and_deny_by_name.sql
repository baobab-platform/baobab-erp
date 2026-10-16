-- P0-04B ERP increment ERP-B (EA v2.2 EA-R03; ADR-SHARED-038; ADR-ERP-022
-- §4.4). The erp/v2 catalogue stays at version 2. For placed AD_Clients only:
--
-- 1. Denied by name. Bank statements, cash journals, inventory, movement,
--    production, and landed cost have no class. Every write to them is refused
--    outright, whichever API, background process or direct SQL makes it. A
--    native process that would create a payment from a bank statement therefore
--    rolls back whole.
-- 2. Vendor-payment recording needs positive provenance. An outbound payment is
--    erp.vendor-payment.record only while it is bound to exactly one
--    independently verified payment-execution evidence record. The record must
--    name the same client, org (and so the placement's legal entity), payee,
--    currency and amount, and its obligation must be a vendor invoice of class
--    erp.vendor-invoice.record. Each record binds at most one payment. Positive
--    evidence is required: the absence of a statement or selection reference is
--    never enough.
-- 3. A vendor payment is allocated only to the obligation its evidence names.
--
-- Evidence is written only by members of baobab_payment_evidence_ingest, never
-- by a superuser and never by iDempiere's runtime role. The only execution
-- authority is SYNTHETIC_ENGINE_LOCAL (Shared erp/v2
-- payment-execution-evidence.schema.json). Vendor-payment recording therefore
-- stays non-activatable for protected and production placements until a Shared
-- revision admits a real authority.
--
-- Ids are NUMERIC(10) in iDempiere: every call site casts (N0004).

-- 1. Denied by name ------------------------------------------------------------------------------

CREATE FUNCTION baobab_native.forbid_uncatalogued_family() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Either side placed refuses: a row can never be moved into or out of a placed client.
  IF (TG_OP <> 'INSERT' AND baobab_native.client_is_placed(OLD.ad_client_id::integer))
     OR (TG_OP <> 'DELETE' AND baobab_native.client_is_placed(NEW.ad_client_id::integer)) THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: % is not a catalogued operation family (ADR-SHARED-038)', TG_TABLE_NAME
      USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['c_bankstatement', 'c_bankstatementline', 'c_cash', 'c_cashline',
                           'm_inventory', 'm_inventoryline', 'm_movement', 'm_movementline',
                           'm_production', 'm_productionline', 'm_productionplan',
                           'c_landedcost', 'c_landedcostallocation'] LOOP
    -- A missing table fails the migration: the refusal must never be silently skipped.
    IF to_regclass('adempiere.' || t) IS NULL THEN
      RAISE EXCEPTION 'ERP-B deny-by-name: adempiere.% is missing', t;
    END IF;
    EXECUTE format('CREATE TRIGGER baobab_forbid_uncatalogued_family BEFORE INSERT OR UPDATE OR DELETE
      ON adempiere.%I FOR EACH ROW EXECUTE FUNCTION baobab_native.forbid_uncatalogued_family()', t);
  END LOOP;
END $$;

-- 2. Payment-execution evidence ---------------------------------------------------------------------

DO $$
BEGIN
  -- Roles are cluster-wide. An operator without CREATEROLE pre-creates it; never LOGIN.
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'baobab_payment_evidence_ingest') THEN
    CREATE ROLE baobab_payment_evidence_ingest NOLOGIN;
  END IF;
END $$;

CREATE TABLE baobab_native.payment_execution_evidence (
  evidence_id uuid PRIMARY KEY,
  execution_authority text NOT NULL CHECK (execution_authority IN ('SYNTHETIC_ENGINE_LOCAL')),
  placement_id uuid NOT NULL,
  placement_version integer NOT NULL,
  responsible_legal_entity_id text NOT NULL,
  ad_client_id integer NOT NULL CHECK (ad_client_id > 0),
  ad_org_id integer NOT NULL CHECK (ad_org_id > 0),
  -- ERP's own resolution of the opaque payee and obligation references.
  payee_reference text NOT NULL CHECK (payee_reference ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'),
  c_bpartner_id integer NOT NULL CHECK (c_bpartner_id > 0),
  obligation_reference text NOT NULL CHECK (obligation_reference ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'),
  c_invoice_id integer NOT NULL CHECK (c_invoice_id > 0),
  currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  c_currency_id integer NOT NULL CHECK (c_currency_id > 0),
  amount numeric NOT NULL CHECK (amount > 0),
  executed_at timestamptz NOT NULL,
  verified_at timestamptz NOT NULL,
  verified_by text NOT NULL CHECK (
    btrim(verified_by) <> '' AND verified_by NOT LIKE 'REQUIRED\_%'
    AND lower(btrim(verified_by)) NOT IN ('system', 'service', 'bootstrap', 'automation', 'auto', 'unknown', 'n/a', 'none')),
  evidence_references text[] NOT NULL CHECK (cardinality(evidence_references) >= 1),
  recorded_by text NOT NULL DEFAULT current_user,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (verified_at >= executed_at),
  FOREIGN KEY (placement_id, placement_version) REFERENCES baobab_native.native_placement (placement_id, version)
);
CREATE INDEX payment_execution_evidence_match_idx
  ON baobab_native.payment_execution_evidence (ad_client_id, ad_org_id, c_bpartner_id, c_currency_id, amount);

-- One payment per evidence record, one evidence record per payment.
CREATE TABLE baobab_native.payment_execution_binding (
  evidence_id uuid PRIMARY KEY REFERENCES baobab_native.payment_execution_evidence (evidence_id),
  c_payment_id integer NOT NULL UNIQUE CHECK (c_payment_id > 0),
  ad_client_id integer NOT NULL,
  bound_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Reads the facts an evidence record must agree with, for an invoker without access to them.
CREATE FUNCTION baobab_native.payment_evidence_facts_hold(p_placement uuid, p_version integer, p_le text,
                                                          p_client integer, p_org integer, p_bpartner integer,
                                                          p_invoice integer, p_currency_id integer, p_currency text)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM baobab_native.native_placement p
                  WHERE p.placement_id = p_placement AND p.version = p_version AND p.effective_to IS NULL
                    AND p.legal_entity_id = p_le AND p.ad_client_id = p_client AND p.ad_org_id = p_org) THEN
    RETURN 'the evidence does not name the open placement version of this legal entity, client and org';
  END IF;
  IF baobab_native.governed_class_of('C_Invoice', p_invoice) IS DISTINCT FROM 'erp.vendor-invoice.record'
     OR NOT EXISTS (SELECT 1 FROM adempiere.c_invoice i
                     WHERE i.c_invoice_id = p_invoice AND i.ad_client_id = p_client AND i.ad_org_id = p_org
                       AND i.c_bpartner_id = p_bpartner AND i.c_currency_id = p_currency_id) THEN
    RETURN 'the obligation is not a vendor invoice of this client, org, payee and currency';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM adempiere.c_currency c
                  WHERE c.c_currency_id = p_currency_id AND c.iso_code = p_currency) THEN
    RETURN 'the currency code does not match the currency';
  END IF;
  RETURN NULL;
END $$;

CREATE FUNCTION baobab_native.payment_evidence_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE problem text;
BEGIN
  -- Only the ingest path: never a superuser (which would also bypass grants), never the runtime role.
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
     OR NOT pg_has_role(current_user, 'baobab_payment_evidence_ingest', 'MEMBER') THEN
    RAISE EXCEPTION 'BAOBAB_NATIVE_FINANCE_DENIED: payment-execution evidence is written only by the ingest role'
      USING ERRCODE = '42501';
  END IF;
  IF NEW.verified_at > clock_timestamp() + interval '1 second' THEN
    RAISE EXCEPTION 'payment-execution evidence cannot be verified in the future' USING ERRCODE = '23514';
  END IF;
  NEW.recorded_by := current_user;
  NEW.recorded_at := clock_timestamp();
  problem := baobab_native.payment_evidence_facts_hold(NEW.placement_id, NEW.placement_version,
               NEW.responsible_legal_entity_id, NEW.ad_client_id, NEW.ad_org_id, NEW.c_bpartner_id,
               NEW.c_invoice_id, NEW.c_currency_id, NEW.currency);
  IF problem IS NOT NULL THEN
    RAISE EXCEPTION 'payment-execution evidence refused: %', problem USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER payment_evidence_insert_guard BEFORE INSERT ON baobab_native.payment_execution_evidence
  FOR EACH ROW EXECUTE FUNCTION baobab_native.payment_evidence_insert_guard();

CREATE FUNCTION baobab_native.payment_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'payment-execution evidence and its bindings are append-only' USING ERRCODE = '42501';
END $$;

CREATE TRIGGER payment_evidence_immutable BEFORE UPDATE OR DELETE ON baobab_native.payment_execution_evidence
  FOR EACH ROW EXECUTE FUNCTION baobab_native.payment_evidence_immutable();
CREATE TRIGGER payment_binding_immutable BEFORE UPDATE OR DELETE ON baobab_native.payment_execution_binding
  FOR EACH ROW EXECUTE FUNCTION baobab_native.payment_evidence_immutable();

-- The single unbound evidence record these payment values would bind, or NULL
-- (none, or several: ambiguity denies). A payment that names an invoice must
-- name the evidence's obligation.
CREATE FUNCTION baobab_native.payment_evidence_candidate(p_client integer, p_org integer, p_bpartner integer,
                                                         p_currency integer, p_amount numeric, p_invoice integer)
RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN count(*) = 1 THEN min(e.evidence_id::text)::uuid END
    FROM baobab_native.payment_execution_evidence e
   WHERE e.ad_client_id = p_client AND e.ad_org_id = p_org AND e.c_bpartner_id = p_bpartner
     AND e.c_currency_id = p_currency AND e.amount = p_amount
     AND (COALESCE(p_invoice, 0) = 0 OR e.c_invoice_id = p_invoice)
     AND NOT EXISTS (SELECT 1 FROM baobab_native.payment_execution_binding b WHERE b.evidence_id = e.evidence_id)
$$;

-- The evidence a STORED payment is bound to, while it still matches the payment's current values.
CREATE FUNCTION baobab_native.payment_bound_evidence(p_payment integer)
RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT e.evidence_id
    FROM adempiere.c_payment p
    JOIN baobab_native.payment_execution_binding b ON b.c_payment_id = p.c_payment_id
                                                  AND b.ad_client_id = p.ad_client_id
    JOIN baobab_native.payment_execution_evidence e ON e.evidence_id = b.evidence_id
   WHERE p.c_payment_id = p_payment AND p.isreceipt = 'N'
     AND e.ad_client_id = p.ad_client_id AND e.ad_org_id = p.ad_org_id
     AND e.c_bpartner_id = p.c_bpartner_id AND e.c_currency_id = p.c_currency_id AND e.amount = p.payamt
     AND (COALESCE(p.c_invoice_id, 0) = 0 OR e.c_invoice_id = p.c_invoice_id)
$$;

-- The provenance the JVM veto checks for an outbound payment being saved, from
-- its own values: a stored, bound payment keeps its evidence only while the
-- values still match; an unbound one needs exactly one unbound candidate.
CREATE FUNCTION baobab_native.vendor_payment_provenance(p_client integer, p_payment integer, p_org integer,
                                                        p_bpartner integer, p_currency integer, p_amount numeric,
                                                        p_invoice integer)
RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN COALESCE(p_payment, 0) > 0 AND EXISTS (SELECT 1 FROM baobab_native.payment_execution_binding b
                                                 WHERE b.c_payment_id = p_payment) THEN
      (SELECT e.evidence_id FROM baobab_native.payment_execution_binding b
         JOIN baobab_native.payment_execution_evidence e ON e.evidence_id = b.evidence_id
        WHERE b.c_payment_id = p_payment AND b.ad_client_id = p_client
          AND e.ad_client_id = p_client AND e.ad_org_id = p_org AND e.c_bpartner_id = p_bpartner
          AND e.c_currency_id = p_currency AND e.amount = p_amount
          AND (COALESCE(p_invoice, 0) = 0 OR e.c_invoice_id = p_invoice))
    ELSE baobab_native.payment_evidence_candidate(p_client, p_org, p_bpartner, p_currency, p_amount, p_invoice)
  END
$$;

-- Binding: the first time an outbound payment of a placed client has exactly one
-- matching unbound evidence record, the two are bound for good. A binding can
-- never be moved; a second payment never consumes the same evidence (primary key).
CREATE FUNCTION baobab_native.bind_payment_execution_evidence() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE candidate uuid;
BEGIN
  IF NEW.isreceipt <> 'N' OR NOT baobab_native.client_is_placed(NEW.ad_client_id::integer)
     OR EXISTS (SELECT 1 FROM baobab_native.payment_execution_binding b
                 WHERE b.c_payment_id = NEW.c_payment_id::integer) THEN
    RETURN NULL;
  END IF;
  candidate := baobab_native.payment_evidence_candidate(NEW.ad_client_id::integer, NEW.ad_org_id::integer,
                 NEW.c_bpartner_id::integer, NEW.c_currency_id::integer, NEW.payamt, NEW.c_invoice_id::integer);
  IF candidate IS NOT NULL THEN
    INSERT INTO baobab_native.payment_execution_binding (evidence_id, c_payment_id, ad_client_id)
    VALUES (candidate, NEW.c_payment_id::integer, NEW.ad_client_id::integer);
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER baobab_bind_payment_execution_evidence AFTER INSERT OR UPDATE ON adempiere.c_payment
  FOR EACH ROW EXECUTE FUNCTION baobab_native.bind_payment_execution_evidence();

-- The catalogued class of a stored source document, or NULL (redefines N0006:
-- an outbound payment now also needs its bound, still-matching evidence).
CREATE OR REPLACE FUNCTION baobab_native.governed_class_of(p_table text, p_record integer)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE result text; sales integer; payables integer; other integer;
BEGIN
  CASE lower(p_table)
    WHEN 'gl_journal' THEN
      SELECT 'erp.gl-journal.post' INTO result FROM adempiere.gl_journal WHERE gl_journal_id = p_record;
    WHEN 'c_order' THEN
      SELECT CASE issotrx WHEN 'Y' THEN 'erp.sales-order.complete' WHEN 'N' THEN 'erp.purchase-order.complete' END
        INTO result FROM adempiere.c_order WHERE c_order_id = p_record;
    WHEN 'm_inout' THEN
      SELECT CASE WHEN issotrx = 'Y' THEN 'erp.shipment.complete'
                  WHEN issotrx = 'N' AND movementtype = 'V+' THEN 'erp.material-receipt.complete' END
        INTO result FROM adempiere.m_inout WHERE m_inout_id = p_record;
    WHEN 'c_invoice' THEN
      SELECT CASE WHEN i.issotrx = 'Y' THEN 'erp.customer-invoice.issue'
                  WHEN i.issotrx = 'N' AND dt.docbasetype = 'API' THEN 'erp.vendor-invoice.record' END
        INTO result
        FROM adempiere.c_invoice i
        LEFT JOIN adempiere.c_doctype dt
          ON dt.c_doctype_id = COALESCE(NULLIF(i.c_doctype_id, 0), i.c_doctypetarget_id)
       WHERE i.c_invoice_id = p_record;
    WHEN 'c_payment' THEN
      SELECT CASE WHEN p.isreceipt = 'Y' THEN 'erp.payment.record'
                  WHEN p.isreceipt = 'N' AND p.isonline = 'N'
                       AND NOT EXISTS (SELECT 1 FROM adempiere.c_payselectioncheck c
                                        WHERE c.c_payment_id = p.c_payment_id)
                       AND baobab_native.payment_bound_evidence(p.c_payment_id::integer) IS NOT NULL
                  THEN 'erp.vendor-payment.record' END
        INTO result FROM adempiere.c_payment p WHERE p.c_payment_id = p_record;
    WHEN 'c_allocationhdr' THEN
      SELECT count(*) FILTER (WHERE s.side = 'SALES'), count(*) FILTER (WHERE s.side = 'PAYABLES'),
             count(*) FILTER (WHERE s.side IS NULL)
        INTO sales, payables, other
        FROM adempiere.c_allocationhdr h
        JOIN adempiere.c_allocationline al ON al.c_allocationhdr_id = h.c_allocationhdr_id
        CROSS JOIN LATERAL (SELECT baobab_native.allocation_line_side(h.ad_client_id::integer,
                              al.c_invoice_id::integer, al.c_payment_id::integer) AS side) s
       WHERE h.c_allocationhdr_id = p_record
         -- a line of another client never joins a placed client's allocation
         AND al.ad_client_id = h.ad_client_id;
      SELECT other + count(*) INTO other FROM adempiere.c_allocationhdr h
        JOIN adempiere.c_allocationline al ON al.c_allocationhdr_id = h.c_allocationhdr_id
       WHERE h.c_allocationhdr_id = p_record AND al.ad_client_id <> h.ad_client_id;
      result := CASE WHEN other = 0 AND sales > 0 AND payables = 0 THEN 'erp.allocation.record'
                     WHEN other = 0 AND payables > 0 AND sales = 0 THEN 'erp.payables-allocation.record' END;
    ELSE
      result := NULL;
  END CASE;
  RETURN result;
END $$;

-- 3. The side of one allocation line (redefines N0006). As before, a SALES line
-- joins only sales invoices and receipts, and a PAYABLES line joins only AP
-- invoices and recordable vendor payments. A line carrying a vendor payment is
-- now PAYABLES only when it also names that payment's evidence obligation as
-- its invoice: a payment is never allocated elsewhere, and never on its own.
CREATE OR REPLACE FUNCTION baobab_native.allocation_line_side(p_client integer, p_invoice integer, p_payment integer)
RETURNS text LANGUAGE sql STABLE AS $$
  WITH sides AS (
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM adempiere.c_invoice i
                                  WHERE i.c_invoice_id = p_invoice AND i.ad_client_id = p_client) THEN 'NONE'
                ELSE CASE baobab_native.governed_class_of('C_Invoice', p_invoice)
                       WHEN 'erp.customer-invoice.issue' THEN 'SALES'
                       WHEN 'erp.vendor-invoice.record' THEN 'PAYABLES' ELSE 'NONE' END END AS side
     WHERE COALESCE(p_invoice, 0) > 0
    UNION ALL
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM adempiere.c_payment p
                                  WHERE p.c_payment_id = p_payment AND p.ad_client_id = p_client) THEN 'NONE'
                ELSE CASE baobab_native.governed_class_of('C_Payment', p_payment)
                       WHEN 'erp.payment.record' THEN 'SALES'
                       WHEN 'erp.vendor-payment.record' THEN
                         CASE WHEN EXISTS (SELECT 1 FROM baobab_native.payment_execution_evidence e
                                            WHERE e.evidence_id = baobab_native.payment_bound_evidence(p_payment)
                                              AND e.c_invoice_id = p_invoice)
                              THEN 'PAYABLES' ELSE 'NONE' END
                       ELSE 'NONE' END END
     WHERE COALESCE(p_payment, 0) > 0)
  SELECT CASE WHEN count(*) = 0 OR bool_or(side = 'NONE') THEN NULL
              WHEN bool_and(side = 'SALES') THEN 'SALES'
              WHEN bool_and(side = 'PAYABLES') THEN 'PAYABLES' END
    FROM sides
$$;

-- Grants: the ingest role writes evidence; nothing else does. The runtime role
-- reads both tables through the functions above.
REVOKE ALL ON baobab_native.payment_execution_evidence FROM PUBLIC;
REVOKE ALL ON baobab_native.payment_execution_binding FROM PUBLIC;
GRANT USAGE ON SCHEMA baobab_native TO baobab_payment_evidence_ingest;
GRANT INSERT, SELECT ON baobab_native.payment_execution_evidence TO baobab_payment_evidence_ingest;
