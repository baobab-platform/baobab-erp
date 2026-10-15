-- Gate B ONLY: the minimal iDempiere columns the P0-04B ERP native
-- migrations and JVM providers read. This is NOT an iDempiere schema and
-- proves nothing about real posting (that is Gate D, a real iDempiere run).
-- ID columns use NUMERIC(10), exactly as the real iDempiere schema does: Gate D
-- found the native triggers failing on real types that an integer fixture hid.
CREATE SCHEMA adempiere;
CREATE TABLE adempiere.ad_client (ad_client_id numeric(10) PRIMARY KEY, isactive char(1) NOT NULL DEFAULT 'Y');
CREATE TABLE adempiere.ad_table (ad_table_id numeric(10) PRIMARY KEY, tablename text NOT NULL);
CREATE TABLE adempiere.c_acctschema (c_acctschema_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  isactive char(1) NOT NULL DEFAULT 'Y');
CREATE TABLE adempiere.c_doctype (c_doctype_id numeric(10) PRIMARY KEY, docbasetype char(3) NOT NULL);
CREATE TABLE adempiere.c_period (c_period_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  startdate date NOT NULL, enddate date NOT NULL);
CREATE TABLE adempiere.c_periodcontrol (c_periodcontrol_id serial PRIMARY KEY, c_period_id numeric(10) NOT NULL,
  docbasetype char(3) NOT NULL, periodstatus char(1) NOT NULL);
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['gl_journal','c_invoice','c_payment','c_allocationhdr','m_inout','c_order',
                           'c_bankstatement','c_cash'] LOOP
    EXECUTE format('CREATE TABLE adempiere.%I (%I numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
      ad_org_id numeric(10) NOT NULL, docstatus char(2) NOT NULL DEFAULT ''DR'', issotrx char(1) NOT NULL DEFAULT ''Y'',
      c_doctype_id numeric(10), dateacct date NOT NULL DEFAULT current_date)', t, t || '_id');
  END LOOP;
END $$;
CREATE TABLE adempiere.gl_journalline (gl_journalline_id numeric(10) PRIMARY KEY, gl_journal_id numeric(10) NOT NULL,
  ad_client_id numeric(10) NOT NULL, ad_org_id numeric(10) NOT NULL);
CREATE TABLE adempiere.c_invoiceline (c_invoiceline_id numeric(10) PRIMARY KEY, c_invoice_id numeric(10) NOT NULL,
  ad_client_id numeric(10) NOT NULL, ad_org_id numeric(10) NOT NULL);
CREATE TABLE adempiere.fact_acct (fact_acct_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  ad_org_id numeric(10) NOT NULL, ad_table_id numeric(10) NOT NULL, record_id numeric(10) NOT NULL,
  c_period_id numeric(10), dateacct date NOT NULL DEFAULT current_date,
  amtacctdr numeric NOT NULL DEFAULT 0, amtacctcr numeric NOT NULL DEFAULT 0);
INSERT INTO adempiere.ad_table VALUES (224, 'GL_Journal'), (318, 'C_Invoice'), (335, 'C_Payment');
-- P0-04B-05: direction and derived costing columns/tables the native fences read.
ALTER TABLE adempiere.c_payment ADD COLUMN isreceipt char(1) NOT NULL DEFAULT 'Y';
CREATE TABLE adempiere.m_inoutline (m_inoutline_id numeric(10) PRIMARY KEY, m_inout_id numeric(10) NOT NULL,
  ad_client_id numeric(10) NOT NULL, ad_org_id numeric(10) NOT NULL);
CREATE TABLE adempiere.c_allocationline (c_allocationline_id numeric(10) PRIMARY KEY,
  c_allocationhdr_id numeric(10) NOT NULL, c_invoice_id numeric(10), c_payment_id numeric(10),
  ad_client_id numeric(10) NOT NULL, ad_org_id numeric(10) NOT NULL);
CREATE TABLE adempiere.m_costdetail (m_costdetail_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  ad_org_id numeric(10) NOT NULL, m_product_id numeric(10) NOT NULL, c_acctschema_id numeric(10) NOT NULL,
  m_costelement_id numeric(10), m_attributesetinstance_id numeric(10) NOT NULL DEFAULT 0,
  m_inoutline_id numeric(10), issotrx char(1) NOT NULL DEFAULT 'Y',
  amt numeric NOT NULL DEFAULT 0, qty numeric NOT NULL DEFAULT 0);
CREATE TABLE adempiere.m_costelement (m_costelement_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  costelementtype char(1) NOT NULL, costingmethod char(1));
INSERT INTO adempiere.m_costelement VALUES (601, 11, 'M', 'A'), (602, 11, 'M', 'S'), (603, 11, 'B', 'S'), (604, 11, 'M', NULL);
ALTER TABLE adempiere.c_acctschema ADD COLUMN m_costtype_id numeric(10) NOT NULL DEFAULT 100;
CREATE TABLE adempiere.m_cost (ad_client_id numeric(10) NOT NULL, ad_org_id numeric(10) NOT NULL,
  m_product_id numeric(10) NOT NULL, c_acctschema_id numeric(10) NOT NULL, m_costtype_id numeric(10) NOT NULL DEFAULT 100,
  m_costelement_id numeric(10) NOT NULL, m_attributesetinstance_id numeric(10) NOT NULL DEFAULT 0,
  currentcostprice numeric NOT NULL DEFAULT 0, currentqty numeric NOT NULL DEFAULT 0,
  PRIMARY KEY (ad_client_id, ad_org_id, m_product_id, c_acctschema_id, m_costtype_id, m_costelement_id,
    m_attributesetinstance_id));
INSERT INTO adempiere.ad_table VALUES (319, 'M_InOut'), (735, 'C_AllocationHdr');
-- P0-04B ERP-A (N0006): the purchase-side columns and tables real iDempiere has.
ALTER TABLE adempiere.m_inout ADD COLUMN movementtype char(2) NOT NULL DEFAULT 'C-';
ALTER TABLE adempiere.c_payment ADD COLUMN isonline char(1) NOT NULL DEFAULT 'N';
ALTER TABLE adempiere.c_invoice ADD COLUMN c_doctypetarget_id numeric(10);
CREATE TABLE adempiere.m_matchpo (m_matchpo_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  ad_org_id numeric(10) NOT NULL, c_orderline_id numeric(10), m_inoutline_id numeric(10), c_invoiceline_id numeric(10));
CREATE TABLE adempiere.m_matchinv (m_matchinv_id numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
  ad_org_id numeric(10) NOT NULL, m_inoutline_id numeric(10), c_invoiceline_id numeric(10) NOT NULL);
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['c_payselection','c_payselectionline','c_payselectioncheck'] LOOP
    EXECUTE format('CREATE TABLE adempiere.%I (%I numeric(10) PRIMARY KEY, ad_client_id numeric(10) NOT NULL,
      ad_org_id numeric(10) NOT NULL)', t, t || '_id');
  END LOOP;
END $$;
ALTER TABLE adempiere.c_payselectioncheck ADD COLUMN c_payment_id numeric(10);
INSERT INTO adempiere.ad_table VALUES (259, 'C_Order'), (472, 'M_MatchInv'), (473, 'M_MatchPO');
