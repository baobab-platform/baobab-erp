-- Gate B ONLY: the minimal iDempiere columns the P0-04B ERP native
-- migrations and JVM providers read. This is NOT an iDempiere schema and
-- proves nothing about real posting (that is Gate D, a real iDempiere run).
CREATE SCHEMA adempiere;
CREATE TABLE adempiere.ad_client (ad_client_id integer PRIMARY KEY, isactive char(1) NOT NULL DEFAULT 'Y');
CREATE TABLE adempiere.ad_table (ad_table_id integer PRIMARY KEY, tablename text NOT NULL);
CREATE TABLE adempiere.c_acctschema (c_acctschema_id integer PRIMARY KEY, ad_client_id integer NOT NULL,
  isactive char(1) NOT NULL DEFAULT 'Y');
CREATE TABLE adempiere.c_doctype (c_doctype_id integer PRIMARY KEY, docbasetype char(3) NOT NULL);
CREATE TABLE adempiere.c_period (c_period_id integer PRIMARY KEY, ad_client_id integer NOT NULL,
  startdate date NOT NULL, enddate date NOT NULL);
CREATE TABLE adempiere.c_periodcontrol (c_periodcontrol_id serial PRIMARY KEY, c_period_id integer NOT NULL,
  docbasetype char(3) NOT NULL, periodstatus char(1) NOT NULL);
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['gl_journal','c_invoice','c_payment','c_allocationhdr','m_inout','c_order',
                           'c_bankstatement','c_cash'] LOOP
    EXECUTE format('CREATE TABLE adempiere.%I (%I integer PRIMARY KEY, ad_client_id integer NOT NULL,
      ad_org_id integer NOT NULL, docstatus char(2) NOT NULL DEFAULT ''DR'', issotrx char(1) NOT NULL DEFAULT ''Y'',
      c_doctype_id integer, dateacct date NOT NULL DEFAULT current_date)', t, t || '_id');
  END LOOP;
END $$;
CREATE TABLE adempiere.gl_journalline (gl_journalline_id integer PRIMARY KEY, gl_journal_id integer NOT NULL,
  ad_client_id integer NOT NULL, ad_org_id integer NOT NULL);
CREATE TABLE adempiere.c_invoiceline (c_invoiceline_id integer PRIMARY KEY, c_invoice_id integer NOT NULL,
  ad_client_id integer NOT NULL, ad_org_id integer NOT NULL);
CREATE TABLE adempiere.fact_acct (fact_acct_id integer PRIMARY KEY, ad_client_id integer NOT NULL,
  ad_org_id integer NOT NULL, ad_table_id integer NOT NULL, record_id integer NOT NULL,
  c_period_id integer, dateacct date NOT NULL DEFAULT current_date,
  amtacctdr numeric NOT NULL DEFAULT 0, amtacctcr numeric NOT NULL DEFAULT 0);
INSERT INTO adempiere.ad_table VALUES (224, 'GL_Journal'), (318, 'C_Invoice'), (335, 'C_Payment');
