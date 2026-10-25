package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/**
 * EA v2.1 Gate B (P0-04B ERP): the REAL placement, readiness, operation and
 * attribution providers and the native migrations' COMMIT fence, on PostgreSQL
 * over JDBC. The adempiere schema is the minimal fixture in
 * tests/native/adempiere_fixture.sql and all CP data is synthetic: this proves
 * database behaviour only, never iDempiere posting (Gate D) or legal standing.
 *
 * Runs only when BAOBAB_NATIVE_TEST_JDBC_URL names a database with the fixture,
 * db/migrate.sh and db/migrate-native.sh applied.
 */
class NativeFinancePostgresGateBTest {
    private static final String URL = System.getenv("BAOBAB_NATIVE_TEST_JDBC_URL");
    private static final int CLIENT = 11;
    private static final int ORG = 11;
    private static final String LE = "SYNTHETIC-GATEB-LE";
    private static final AtomicInteger IDS = new AtomicInteger((int) (System.nanoTime() % 1_000_000) + 1_000_000);
    private static String placementId;

    private static Connection open() throws SQLException {
        return DriverManager.getConnection(URL);
    }

    private static Connection transaction() throws SQLException {
        Connection c = open();
        c.setAutoCommit(false);
        return c;
    }

    @BeforeAll
    static void synthesiseGovernedFacts() throws Exception {
        assumeTrue(URL != null && !URL.isBlank(), "BAOBAB_NATIVE_TEST_JDBC_URL not set");
        try (Connection c = open(); Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.ad_client VALUES (11, 'Y') ON CONFLICT DO NOTHING");
            s.execute("INSERT INTO adempiere.ad_org (ad_org_id, ad_client_id) VALUES (11, 11) ON CONFLICT DO NOTHING");
            s.execute("INSERT INTO adempiere.c_acctschema VALUES (101, 11, 'Y') ON CONFLICT DO NOTHING");
            s.execute("INSERT INTO adempiere.c_doctype VALUES (201, 'GLJ') ON CONFLICT DO NOTHING");
            s.execute("INSERT INTO adempiere.c_period VALUES (301, 11, current_date - 1, current_date + 1) ON CONFLICT DO NOTHING");
            s.execute("INSERT INTO adempiere.c_periodcontrol (c_period_id, docbasetype, periodstatus) "
                    + "SELECT 301, 'GLJ', 'O' WHERE NOT EXISTS (SELECT 1 FROM adempiere.c_periodcontrol WHERE c_period_id = 301)");
            s.execute("""
                INSERT INTO baobab.financial_configuration_baseline (legal_entity_id, version, functional_currency,
                  fiscal_year_start_month, chart_of_accounts_template, accounting_schema, tax_profile, costing_method,
                  effective_from, approved_by, approved_at, evidence_reference)
                VALUES ('%s', 1, 'UGX', 1, 'synthetic-chart', 'synthetic-schema', 'synthetic-tax', 'AVERAGE',
                  current_date - 30, 'Finance Approver', now(), 'synthetic:gate-b/baseline')
                ON CONFLICT DO NOTHING""".formatted(LE));
            var r = s.executeQuery("SELECT placement_id::text FROM baobab_native.native_placement "
                    + "WHERE ad_client_id = 11 AND ad_org_id = 11 AND effective_to IS NULL");
            if (r.next()) {
                placementId = r.getString(1);
            } else {
                placementId = UUID.randomUUID().toString();
                s.execute("""
                    INSERT INTO baobab_native.native_placement (placement_id, version, tenant_id, engine_instance_id,
                      operating_organisation_id, legal_entity_id, market, ad_client_id, ad_org_id, effective_from,
                      approved_by, checked_by, evidence_reference, erp_assignment_reference)
                    VALUES ('%s', 1, 'tn_gateb01', 'ei_gateb01', '2c8e4f6a-1b3d-4e5f-8a7c-9d0e1f2a3b4c', '%s', 'UG',
                      11, 11, now() - interval '1 day', 'Placement Maker', 'Placement Checker',
                      'synthetic:gate-b/placement', 'synthetic:plan/1/v1')""".formatted(placementId, LE));
            }
        }
    }

    private static int newJournal(Connection c) throws SQLException {
        int id = IDS.incrementAndGet();
        try (Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.gl_journal (gl_journal_id, ad_client_id, ad_org_id, c_doctype_id) "
                    + "VALUES (" + id + ", 11, 11, 201)");
        }
        return id;
    }

    private static NativeOperation factLine(int journal, String trx) {
        return new NativeOperation(NativeOperation.GL_JOURNAL, "GL_Journal", journal,
                new NativeRecord("Fact_Acct", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW", trx,
                        col -> switch (col) {
                            case "AD_Table_ID" -> 224;
                            case "Record_ID" -> journal;
                            case "C_Period_ID" -> 301;
                            default -> null;
                        }));
    }

    private static NativeFinanceAttribution.Decision decision(Instant usableUntil) {
        return new NativeFinanceAttribution.Decision(UUID.randomUUID().toString(), UUID.randomUUID().toString(),
                UUID.randomUUID().toString(), null, "synthetic:gate-b/mandate-evidence",
                Instant.parse("2026-10-01T00:00:00Z"), usableUntil);
    }

    private static void insertFact(Connection c, int journal) throws SQLException {
        try (Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.fact_acct (fact_acct_id, ad_client_id, ad_org_id, ad_table_id, record_id, "
                    + "c_period_id, amtacctdr) VALUES (" + IDS.incrementAndGet() + ", 11, 11, 224, " + journal + ", 301, 10)");
        }
    }

    private static int count(String sql) throws SQLException {
        try (Connection c = open(); Statement s = c.createStatement(); var r = s.executeQuery(sql)) {
            r.next();
            return r.getInt(1);
        }
    }

    /** Authorise one ledger line through the real providers on connection c. */
    private static NativePlacement authorise(Connection c, NativeOperation op, Instant until) throws Exception {
        NativeConnections same = trx -> c;
        NativeOperation classified = new NativeOperationResolver(same).classify(op.record());
        assertEquals(op.operationClass(), classified.operationClass());
        assertEquals(op.sourceRecordId(), classified.sourceRecordId());
        NativePlacement placement = new PlacementContextSource(same).currentPlacement(classified);
        assertNotNull(placement, "provenance-backed placement");
        var baseline = new BaselineFinanceReadiness(same).currentBaseline(classified, placement);
        assertNotNull(baseline, "Finance readiness");
        new NativeFinanceAttribution(same).append(classified, placement, decision(until), baseline);
        return placement;
    }

    @Test
    void authorisedLedgerLineCommitsAtomicallyWithItsAttribution() throws Exception {
        int journal;
        try (Connection c = transaction()) {
            journal = newJournal(c);
            c.commit();
        }
        try (Connection c = transaction()) {
            NativePlacement p = authorise(c, factLine(journal, "gate-b-commit"), Instant.now().plusSeconds(25));
            assertEquals(placementId, p.placementId());
            insertFact(c, journal);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.fact_acct WHERE record_id = " + journal));
        assertEquals(1, count("SELECT count(*) FROM baobab_native.finance_authority_attribution "
                + "WHERE source_record_id = " + journal + " AND finance_baseline_version = 1"));
    }

    @Test
    void rollbackLeavesNeitherLedgerNorAttribution() throws Exception {
        int journal;
        try (Connection c = transaction()) {
            journal = newJournal(c);
            c.commit();
        }
        try (Connection c = transaction()) {
            authorise(c, factLine(journal, "gate-b-rollback"), Instant.now().plusSeconds(25));
            insertFact(c, journal);
            c.rollback();
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.fact_acct WHERE record_id = " + journal));
        assertEquals(0, count("SELECT count(*) FROM baobab_native.finance_authority_attribution WHERE source_record_id = " + journal));
    }

    @Test
    void directSqlLedgerAndCompletionAreRefusedAtCommit() throws Exception {
        int journal;
        try (Connection c = transaction()) {
            journal = newJournal(c);
            c.commit();
        }
        try (Connection c = transaction()) {
            insertFact(c, journal);
            SQLException e = assertThrows(SQLException.class, c::commit);
            assertTrue(e.getMessage().contains("BAOBAB_NATIVE_FINANCE_DENIED"));
        }
        try (Connection c = transaction(); Statement s = c.createStatement()) {
            s.execute("UPDATE adempiere.gl_journal SET docstatus = 'CO' WHERE gl_journal_id = " + journal);
            assertThrows(SQLException.class, c::commit);
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.fact_acct WHERE record_id = " + journal));
    }

    @Test
    void documentInsertedAlreadyCompletedIsRefusedAtCommit() throws Exception {
        for (String status : new String[] {"CO", "CL"}) {
            int id = IDS.incrementAndGet();
            try (Connection c = transaction(); Statement s = c.createStatement()) {
                s.execute("INSERT INTO adempiere.c_invoice (c_invoice_id, ad_client_id, ad_org_id, docstatus) VALUES ("
                        + id + ", 11, 11, '" + status + "')");
                SQLException e = assertThrows(SQLException.class, c::commit, status);
                assertTrue(e.getMessage().contains("BAOBAB_NATIVE_FINANCE_DENIED"));
            }
            assertEquals(0, count("SELECT count(*) FROM adempiere.c_invoice WHERE c_invoice_id = " + id));
        }
    }

    @Test
    void contractLengthEvidenceIsStored() throws Exception {
        for (int length : new int[] {1, 500}) {
            int journal;
            try (Connection c = transaction()) {
                journal = newJournal(c);
                c.commit();
            }
            try (Connection c = transaction()) {
                NativeConnections same = trx -> c;
                NativeOperation op = new NativeOperationResolver(same).classify(factLine(journal, "gate-b-ev").record());
                NativePlacement p = new PlacementContextSource(same).currentPlacement(op);
                var baseline = new BaselineFinanceReadiness(same).currentBaseline(op, p);
                var d = decision(Instant.now().plusSeconds(25));
                var evidence = new NativeFinanceAttribution.Decision(d.decisionId(), d.contextId(), d.mandateId(), null,
                        "e".repeat(length), d.mandateEffectiveFrom(), d.usableUntil());
                new NativeFinanceAttribution(same).append(op, p, evidence, baseline);
                insertFact(c, journal);
                c.commit();
            }
            assertEquals(1, count("SELECT count(*) FROM baobab_native.finance_authority_attribution "
                    + "WHERE source_record_id = " + journal + " AND length(evidence_reference) = " + length));
        }
    }

    @Test
    void expiredAuthorityIsRefusedAndLapsingAuthorityFailsAtCommit() throws Exception {
        int journal;
        try (Connection c = transaction()) {
            journal = newJournal(c);
            c.commit();
        }
        try (Connection c = transaction()) {
            assertThrows(SQLException.class,
                    () -> authorise(c, factLine(journal, "gate-b-expired"), Instant.now().minusSeconds(1)));
            c.rollback();
        }
        try (Connection c = transaction()) {
            authorise(c, factLine(journal, "gate-b-lapse"), Instant.now().plusSeconds(1));
            insertFact(c, journal);
            Thread.sleep(1500); // the posting transaction outlives its lease
            assertThrows(SQLException.class, c::commit);
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.fact_acct WHERE record_id = " + journal));
    }

    @Test
    void authorityNeverCrossesTransactionsAndRetryNeedsFreshAuthority() throws Exception {
        int a, b;
        try (Connection c = transaction()) {
            a = newJournal(c);
            b = newJournal(c);
            c.commit();
        }
        try (Connection ta = transaction(); Connection tb = transaction()) {
            authorise(ta, factLine(a, "gate-b-a"), Instant.now().plusSeconds(25));
            insertFact(ta, a);
            insertFact(tb, a); // concurrent transaction relying on A's authority
            assertThrows(SQLException.class, tb::commit);
            ta.commit();
        }
        // Retry after a committed posting: the next transaction holds nothing.
        try (Connection c = transaction()) {
            assertFalse(new NativeFinanceAttribution(trx -> c).hasCurrent(factLine(a, "gate-b-retry")));
            insertFact(c, a);
            assertThrows(SQLException.class, c::commit);
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.fact_acct WHERE record_id = " + a));
        assertEquals(0, count("SELECT count(*) FROM adempiere.fact_acct WHERE record_id = " + b));
    }

    @Test
    void unplacedOrgClosedPlacementAndPurchaseSideHaveNoAuthorityPath() throws Exception {
        try (Connection c = transaction(); Statement s = c.createStatement()) {
            assertThrows(SQLException.class, () -> s.execute(
                    "INSERT INTO adempiere.gl_journal (gl_journal_id, ad_client_id, ad_org_id) VALUES ("
                            + IDS.incrementAndGet() + ", 11, 77)"));
            c.rollback();
        }
        try (Connection c = transaction()) {
            int invoice = IDS.incrementAndGet();
            try (Statement s = c.createStatement()) {
                s.execute("INSERT INTO adempiere.c_invoice (c_invoice_id, ad_client_id, ad_org_id, issotrx) VALUES ("
                        + invoice + ", 11, 11, 'N')");
            }
            NativeRecord vendorLine = new NativeRecord("C_InvoiceLine", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW",
                    "gate-b-ap", col -> "C_Invoice_ID".equals(col) ? invoice : null);
            assertNull(new NativeOperationResolver(trx -> c).classify(vendorLine), "purchase side has no class");
            c.rollback();
        }
        // A document whose provenance placement is no longer in force has no placement.
        try (Connection c = transaction()) {
            int journal = newJournal(c);
            NativeOperation op = factLine(journal, "gate-b-closed");
            try (Statement s = c.createStatement()) {
                s.execute("UPDATE baobab_native.native_placement SET effective_to = clock_timestamp() "
                        + "WHERE placement_id = '" + placementId + "' AND effective_to IS NULL");
            }
            assertNull(new PlacementContextSource(trx -> c).currentPlacement(op));
            c.rollback(); // keep the shared synthetic placement open for other tests
        }
    }

    @Test
    void anotherClientsOpenPeriodDoesNotMakeThisClientReady() throws Exception {
        try (Connection c = transaction()) {
            try (Statement s = c.createStatement()) {
                s.execute("INSERT INTO adempiere.c_period VALUES (302, 12, current_date - 1, current_date + 1)");
                s.execute("INSERT INTO adempiere.c_periodcontrol (c_period_id, docbasetype, periodstatus) VALUES (302, 'GLJ', 'O')");
            }
            int journal = newJournal(c);
            NativeOperation foreignPeriod = new NativeOperation(NativeOperation.GL_JOURNAL, "GL_Journal", journal,
                    new NativeRecord("Fact_Acct", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW", "gate-b-period",
                            col -> switch (col) {
                                case "AD_Table_ID" -> 224;
                                case "Record_ID" -> journal;
                                case "C_Period_ID" -> 302;
                                default -> null;
                            }));
            NativePlacement p = new PlacementContextSource(trx -> c).currentPlacement(foreignPeriod);
            assertNotNull(p);
            assertNull(new BaselineFinanceReadiness(trx -> c).currentBaseline(foreignPeriod, p));
            assertNotNull(new BaselineFinanceReadiness(trx -> c).currentBaseline(factLine(journal, "gate-b-period"), p));
            c.rollback();
        }
    }

    @Test
    void withdrawnBaselineIsNotReady() throws Exception {
        try (Connection c = transaction()) {
            int journal = newJournal(c);
            NativeOperation op = factLine(journal, "gate-b-withdrawn");
            NativePlacement p = new PlacementContextSource(trx -> c).currentPlacement(op);
            try (Statement s = c.createStatement()) {
                s.execute("""
                    INSERT INTO baobab.financial_configuration_baseline_withdrawal (legal_entity_id, version,
                      withdrawn_by, withdrawn_at, reason, evidence_reference)
                    VALUES ('%s', 1, 'Finance Approver', now(), 'synthetic withdrawal', 'synthetic:gate-b/withdrawal')
                    """.formatted(LE));
            }
            assertNull(new BaselineFinanceReadiness(trx -> c).currentBaseline(op, p));
            c.rollback();
        }
    }

    // ---- P0-04B-05: direction and derived costing --------------------------------------------

    private static int insertDoc(Connection c, String relation, String direction, String value) throws SQLException {
        int id = IDS.incrementAndGet();
        try (Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere." + relation + " (" + relation + "_id, ad_client_id, ad_org_id, c_doctype_id, "
                    + direction + ") VALUES (" + id + ", 11, 11, 201, '" + value + "')");
        }
        return id;
    }

    private static NativeRecord header(String table, int id, String trx, String direction, String value) {
        return new NativeRecord(table, CLIENT, ORG, id, "document:TIMING_BEFORE_COMPLETE", trx,
                col -> col.equals(direction) ? value : null);
    }

    private static void denied(Connection c) {
        SQLException e = assertThrows(SQLException.class, c::commit);
        assertTrue(e.getMessage().contains("BAOBAB_NATIVE_FINANCE_DENIED"), e.getMessage());
    }

    @Test
    void outboundPaymentIsRecordedOnlyAndForgedSalesAuthorityCannotCompleteIt() throws Exception {
        int payment;
        int invoice;
        try (Connection c = transaction()) {
            invoice = vendorInvoice(c);
            c.commit();
        }
        ingestEvidence(invoice, "125.00", PARTNER, CURRENCY, "UGX");
        try (Connection c = transaction()) {
            payment = vendorPayment(c, invoice, "125.00", true);
            c.commit();
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            // ERP-A (ADR-SHARED-037): an outbound payment that is neither online
            // nor from a payment selection is RECORDED under its own class only,
            // and (ERP-B) only with its bound execution evidence.
            assertEquals(NativeOperation.VENDOR_PAYMENT,
                    resolver.classify(payment(payment, invoice, "125.00", "IsOnline", "N")).operationClass());
            assertNull(resolver.classify(payment(payment, invoice, "125.00", "IsOnline", "Y")),
                    "an online outbound payment is a disbursement instruction");
            assertNull(resolver.classify(payment(payment, invoice, "125.00")),
                    "a missing online flag denies");
            assertNull(resolver.classify(header("C_Payment", payment, "gate-b-out", "IsReceipt", null)),
                    "a missing direction denies");
            assertEquals(NativeOperation.VENDOR_PAYMENT, resolver.classify(new NativeRecord("Fact_Acct", CLIENT, ORG, 0,
                    "model:TYPE_BEFORE_NEW", "gate-b-out",
                    col -> switch (col) { case "AD_Table_ID" -> 335; case "Record_ID" -> payment; default -> null; }))
                    .operationClass(), "an outbound payment's ledger is recorded under its own class");
            // An attribution forged for the RECEIPT class cannot complete it at COMMIT.
            NativeOperation forged = new NativeOperation(NativeOperation.PAYMENT, "C_Payment", payment,
                    header("C_Payment", payment, "gate-b-out", "IsReceipt", "N"));
            NativeConnections same = trx -> c;
            NativePlacement p = new PlacementContextSource(same).currentPlacement(forged);
            new NativeFinanceAttribution(same).append(forged, p, decision(Instant.now().plusSeconds(25)),
                    new NativeFinanceReadiness.FinanceBaseline(LE, 1));
            try (Statement s = c.createStatement()) {
                s.execute("UPDATE adempiere.c_payment SET docstatus = 'CO' WHERE c_payment_id = " + payment);
            }
            denied(c);
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.c_payment WHERE docstatus = 'CO' AND c_payment_id = " + payment));
    }

    @Test
    void governedDirectionCannotBeChanged() throws Exception {
        int receipt;
        int invoice;
        try (Connection c = transaction()) {
            receipt = insertDoc(c, "c_payment", "isreceipt", "Y");
            invoice = insertDoc(c, "c_invoice", "issotrx", "Y");
            c.commit();
        }
        for (String sql : new String[] {
                "UPDATE adempiere.c_payment SET isreceipt = 'N' WHERE c_payment_id = " + receipt,
                "UPDATE adempiere.c_invoice SET issotrx = 'N' WHERE c_invoice_id = " + invoice}) {
            try (Connection c = transaction(); Statement s = c.createStatement()) {
                SQLException e = assertThrows(SQLException.class, () -> s.execute(sql));
                assertTrue(e.getMessage().contains("cannot change direction"), e.getMessage());
            }
        }
    }

    @Test
    void completionNeedsAnAttributionOfTheDocumentsOwnClass() throws Exception {
        int invoice;
        try (Connection c = transaction()) {
            invoice = insertDoc(c, "c_invoice", "issotrx", "Y");
            c.commit();
        }
        try (Connection c = transaction()) {
            // A current attribution of ANOTHER class for this invoice is not authority to issue it.
            NativeOperation wrongClass = new NativeOperation(NativeOperation.GL_JOURNAL, "C_Invoice", invoice,
                    header("C_Invoice", invoice, "gate-b-class", "IsSOTrx", "Y"));
            NativeConnections same = trx -> c;
            NativePlacement p = new PlacementContextSource(same).currentPlacement(wrongClass);
            new NativeFinanceAttribution(same).append(wrongClass, p, decision(Instant.now().plusSeconds(25)),
                    new NativeFinanceReadiness.FinanceBaseline(LE, 1));
            try (Statement s = c.createStatement()) {
                s.execute("UPDATE adempiere.c_invoice SET docstatus = 'CO' WHERE c_invoice_id = " + invoice);
            }
            denied(c);
        }
    }

    @Test
    void allocationToAVendorInvoiceHasNoClass() throws Exception {
        try (Connection c = transaction()) {
            int vendorInvoice = insertDoc(c, "c_invoice", "issotrx", "N");
            int receipt = insertDoc(c, "c_payment", "isreceipt", "Y");
            int allocation = IDS.incrementAndGet();
            try (Statement s = c.createStatement()) {
                s.execute("INSERT INTO adempiere.c_allocationhdr (c_allocationhdr_id, ad_client_id, ad_org_id) VALUES ("
                        + allocation + ", 11, 11)");
                s.execute("INSERT INTO adempiere.c_allocationline VALUES (" + IDS.incrementAndGet() + ", " + allocation
                        + ", " + vendorInvoice + ", " + receipt + ", 11, 11)");
            }
            var resolver = new NativeOperationResolver(trx -> c);
            assertNull(resolver.classify(new NativeRecord("C_AllocationHdr", CLIENT, ORG, allocation,
                    "document:TIMING_BEFORE_COMPLETE", "gate-b-alloc", col -> null)));
            assertNull(resolver.classify(new NativeRecord("C_AllocationLine", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW",
                    "gate-b-alloc", col -> switch (col) {
                        case "C_AllocationHdr_ID" -> allocation; case "C_Invoice_ID" -> vendorInvoice;
                        case "C_Payment_ID" -> receipt; default -> null; })));
            c.rollback();
        }
    }

    private static NativeRecord costDetail(int line, String soTrx, String trx) {
        return new NativeRecord("M_CostDetail", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW", trx, col -> switch (col) {
            case "M_InOutLine_ID" -> line;
            case "IsSOTrx" -> soTrx;
            case "M_Product_ID" -> 501;
            case "C_AcctSchema_ID" -> 101;
            case "M_CostElement_ID" -> 601;
            default -> null;
        });
    }

    private static int shipmentLine(Connection c, String soTrx) throws SQLException {
        int shipment = insertDoc(c, "m_inout", "issotrx", soTrx);
        int line = IDS.incrementAndGet();
        try (Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.m_inoutline VALUES (" + line + ", " + shipment + ", 11, 11)");
        }
        return line;
    }

    private static void writeCost(Connection c, int line) throws SQLException {
        try (Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.m_costdetail (m_costdetail_id, ad_client_id, ad_org_id, m_product_id, "
                    + "c_acctschema_id, m_costelement_id, m_inoutline_id) VALUES (" + IDS.incrementAndGet()
                    + ", 11, 11, 501, 101, 601, " + line + ")");
            s.execute("INSERT INTO adempiere.m_cost (ad_client_id, ad_org_id, m_product_id, c_acctschema_id, "
                    + "m_costelement_id, currentqty) VALUES (11, 0, 501, 101, 601, -1) ON CONFLICT "
                    + "(ad_client_id, ad_org_id, m_product_id, c_acctschema_id, m_costtype_id, m_costelement_id, "
                    + "m_attributesetinstance_id) "
                    + "DO UPDATE SET currentqty = adempiere.m_cost.currentqty - 1");
        }
    }

    @Test
    void shipmentCostingCommitsOnlyAsAConsequenceOfItsAuthorisedRoot() throws Exception {
        int line;
        try (Connection c = transaction()) {
            line = shipmentLine(c, "Y");
            c.commit();
        }
        try (Connection c = transaction()) {
            NativeConnections same = trx -> c;
            NativeOperation root = new NativeOperationResolver(same).classify(costDetail(line, "Y", "gate-b-cost"));
            assertNotNull(root, "a sales shipment line roots its cost detail");
            assertEquals(NativeOperation.SHIPMENT, root.operationClass());
            assertEquals("M_InOut", root.sourceTable());
            NativePlacement p = new PlacementContextSource(same).currentPlacement(root);
            new NativeFinanceAttribution(same).append(root, p, decision(Instant.now().plusSeconds(25)),
                    new NativeFinanceReadiness.FinanceBaseline(LE, 1));
            new NativeDerivedWrites(same).appendCostDetail(root);
            NativeDerivedWrites derived = new NativeDerivedWrites(same);
            assertTrue(derived.costCovered(bucket(601, 100, 0)), "the cost detail's own bucket is covered");
            assertFalse(derived.costCovered(bucket(602, 100, 0)), "another cost element is not covered");
            assertFalse(derived.costCovered(bucket(601, 999, 0)), "another cost type is not covered");
            assertFalse(derived.costCovered(bucket(601, 100, 77)), "another attribute set instance is not covered");
            writeCost(c, line);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.m_costdetail WHERE m_inoutline_id = " + line));
    }

    @Test
    void costingWithoutAnAuthorisedRootIsDenied() throws Exception {
        int salesLine;
        int purchaseLine;
        try (Connection c = transaction()) {
            salesLine = shipmentLine(c, "Y");
            purchaseLine = shipmentLine(c, "N");
            c.commit();
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            assertNull(resolver.classify(costDetail(purchaseLine, "N", "gate-b-nocost")), "a material receipt is not catalogued");
            assertNull(resolver.classify(costDetail(salesLine, "N", "gate-b-nocost")), "the cost detail's own direction must hold");
            NativeRecord twoSources = new NativeRecord("M_CostDetail", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW", "gate-b-nocost",
                    col -> switch (col) { case "M_InOutLine_ID" -> salesLine; case "C_InvoiceLine_ID" -> 9; case "IsSOTrx" -> "Y";
                        default -> null; });
            assertNull(resolver.classify(twoSources), "an ambiguous cost source denies");
            // Without the root's attribution in this transaction nothing derives.
            NativeOperation root = resolver.classify(costDetail(salesLine, "Y", "gate-b-nocost"));
            assertThrows(SQLException.class, () -> new NativeDerivedWrites(trx -> c).appendCostDetail(root));
            c.rollback();
        }
        // Direct SQL costing is refused at COMMIT.
        try (Connection c = transaction()) {
            writeCost(c, salesLine);
            denied(c);
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.m_costdetail WHERE m_inoutline_id = " + salesLine));
    }

    @Test
    void expiringRootRollsBackItsCosting() throws Exception {
        int line;
        try (Connection c = transaction()) {
            line = shipmentLine(c, "Y");
            c.commit();
        }
        try (Connection c = transaction()) {
            NativeConnections same = trx -> c;
            NativeOperation root = new NativeOperationResolver(same).classify(costDetail(line, "Y", "gate-b-lapse"));
            NativePlacement p = new PlacementContextSource(same).currentPlacement(root);
            new NativeFinanceAttribution(same).append(root, p, decision(Instant.now().plusMillis(1500)),
                    new NativeFinanceReadiness.FinanceBaseline(LE, 1));
            new NativeDerivedWrites(same).appendCostDetail(root);
            writeCost(c, line);
            Thread.sleep(2000);
            denied(c);
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.m_costdetail WHERE m_inoutline_id = " + line));
    }

    private static NativeRecord bucket(int element, int costType, int asi) {
        return new NativeRecord("M_Cost", CLIENT, 0, 0, "model:TYPE_BEFORE_CHANGE", "gate-b-cost", col -> switch (col) {
            case "M_Product_ID" -> 501; case "C_AcctSchema_ID" -> 101; case "M_CostElement_ID" -> element;
            case "M_CostType_ID" -> costType; case "M_AttributeSetInstance_ID" -> asi; default -> null; });
    }

    @Test
    void anotherCostBucketCannotPiggybackOnAShipmentCostDetail() throws Exception {
        int line;
        try (Connection c = transaction()) {
            line = shipmentLine(c, "Y");
            c.commit();
        }
        try (Connection c = transaction()) {
            NativeConnections same = trx -> c;
            NativeOperation root = new NativeOperationResolver(same).classify(costDetail(line, "Y", "gate-b-bucket"));
            new NativeFinanceAttribution(same).append(root, new PlacementContextSource(same).currentPlacement(root),
                    decision(Instant.now().plusSeconds(25)), new NativeFinanceReadiness.FinanceBaseline(LE, 1));
            new NativeDerivedWrites(same).appendCostDetail(root);
            writeCost(c, line);
            try (Statement s = c.createStatement()) {
                s.execute("INSERT INTO adempiere.m_cost (ad_client_id, ad_org_id, m_product_id, c_acctschema_id, "
                        + "m_costelement_id, currentcostprice) VALUES (11, 0, 501, 101, 602, 99) ON CONFLICT DO NOTHING");
                s.execute("UPDATE adempiere.m_cost SET currentcostprice = 98 WHERE m_costelement_id = 602 AND m_product_id = 501");
            }
            denied(c);
        }
    }

    @Test
    void deletingCostRowsWithoutAuthorityIsRefusedAtCommit() throws Exception {
        int line;
        try (Connection c = transaction()) {
            line = shipmentLine(c, "Y");
            c.commit();
        }
        try (Connection c = transaction()) {
            NativeConnections same = trx -> c;
            NativeOperation root = new NativeOperationResolver(same).classify(costDetail(line, "Y", "gate-b-del"));
            new NativeFinanceAttribution(same).append(root, new PlacementContextSource(same).currentPlacement(root),
                    decision(Instant.now().plusSeconds(25)), new NativeFinanceReadiness.FinanceBaseline(LE, 1));
            new NativeDerivedWrites(same).appendCostDetail(root);
            writeCost(c, line);
            c.commit();
        }
        for (String sql : new String[] {
                "DELETE FROM adempiere.m_costdetail WHERE m_inoutline_id = " + line,
                "DELETE FROM adempiere.m_cost WHERE m_product_id = 501 AND m_costelement_id = 601"}) {
            try (Connection c = transaction(); Statement s = c.createStatement()) {
                assertTrue(s.executeUpdate(sql) > 0, sql);
                denied(c);
            }
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.m_costdetail WHERE m_inoutline_id = " + line));
    }

    @Test
    void completedAllocationCannotBeRepointedByDirectSql() throws Exception {
        int allocation = IDS.incrementAndGet();
        int vendorInvoice;
        int receipt;
        try (Connection c = transaction(); Statement s = c.createStatement()) {
            vendorInvoice = insertDoc(c, "c_invoice", "issotrx", "N");
            receipt = insertDoc(c, "c_payment", "isreceipt", "Y");
            s.execute("INSERT INTO adempiere.c_allocationhdr (c_allocationhdr_id, ad_client_id, ad_org_id) VALUES ("
                    + allocation + ", 11, 11)");
            c.commit();
        }
        for (String sql : new String[] {
                "INSERT INTO adempiere.c_allocationline VALUES (" + IDS.incrementAndGet() + ", " + allocation + ", "
                        + vendorInvoice + ", " + receipt + ", 11, 11)",
                "INSERT INTO adempiere.c_allocationline VALUES (" + IDS.incrementAndGet() + ", " + allocation + ", NULL, "
                        + receipt + ", 11, 11)"}) {
            try (Connection c = transaction(); Statement s = c.createStatement()) {
                s.execute(sql);
                denied(c);
            }
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.c_allocationline WHERE c_allocationhdr_id = " + allocation));
    }

    // --- P0-04B ERP-A (N0006, ADR-SHARED-037): purchase side and vendor-payment recording ---

    private static NativeRecord record(String table, int id, String trx, String... columnValues) {
        java.util.Map<String, Object> values = new java.util.HashMap<>();
        for (int i = 0; i + 1 < columnValues.length; i += 2) values.put(columnValues[i], columnValues[i + 1]);
        return new NativeRecord(table, CLIENT, ORG, id, "document:TIMING_BEFORE_COMPLETE", trx, values::get);
    }

    private static void sql(Connection c, String statement) throws SQLException {
        try (Statement s = c.createStatement()) {
            s.execute(statement);
        }
    }

    private static int insertPurchase(Connection c, String relation, String extraColumns, String extraValues)
            throws SQLException {
        int id = IDS.incrementAndGet();
        sql(c, "INSERT INTO adempiere." + relation + " (" + relation + "_id, ad_client_id, ad_org_id, issotrx"
                + extraColumns + ") VALUES (" + id + ", 11, 11, 'N'" + extraValues + ")");
        return id;
    }

    /** Append an attribution for op's class through the real placement, readiness and attribution providers. */
    private static void attribute(Connection c, NativeOperation op) throws Exception {
        NativeConnections same = trx -> c;
        NativePlacement placement = new PlacementContextSource(same).currentPlacement(op);
        assertNotNull(placement, "provenance-backed placement");
        new NativeFinanceAttribution(same).append(op, placement, decision(Instant.now().plusSeconds(25)),
                new NativeFinanceReadiness.FinanceBaseline(LE, 1));
    }

    private static String storedClass(String table, int id) throws SQLException {
        try (Connection c = open(); var s = c.prepareStatement("SELECT baobab_native.governed_class_of(?, ?)")) {
            s.setString(1, table);
            s.setInt(2, id);
            try (var r = s.executeQuery()) {
                r.next();
                return r.getString(1);
            }
        }
    }

    @Test
    void purchaseDocumentsAreClassifiedByTheirOwnValuesAndStoredRows() throws Exception {
        int order, receipt, vendorReturn, invoice, creditMemo;
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API'), (203, 'APC') ON CONFLICT DO NOTHING");
            order = insertPurchase(c, "c_order", "", "");
            receipt = insertPurchase(c, "m_inout", ", movementtype", ", 'V+'");
            vendorReturn = insertPurchase(c, "m_inout", ", movementtype", ", 'V-'");
            invoice = insertPurchase(c, "c_invoice", ", c_doctypetarget_id, c_doctype_id", ", 202, 0");
            creditMemo = insertPurchase(c, "c_invoice", ", c_doctypetarget_id, c_doctype_id", ", 203, 0");
            c.commit();
        }
        assertEquals(NativeOperation.PURCHASE_ORDER, storedClass("C_Order", order));
        assertEquals(NativeOperation.MATERIAL_RECEIPT, storedClass("M_InOut", receipt));
        assertNull(storedClass("M_InOut", vendorReturn), "a vendor return is not a goods receipt");
        assertEquals(NativeOperation.VENDOR_INVOICE, storedClass("C_Invoice", invoice));
        assertNull(storedClass("C_Invoice", creditMemo), "an AP credit memo has no class");
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            assertEquals(NativeOperation.PURCHASE_ORDER,
                    resolver.classify(record("C_Order", order, "gate-b-po", "IsSOTrx", "N")).operationClass());
            assertEquals(NativeOperation.MATERIAL_RECEIPT, resolver.classify(
                    record("M_InOut", receipt, "gate-b-po", "IsSOTrx", "N", "MovementType", "V+")).operationClass());
            assertNull(resolver.classify(record("M_InOut", vendorReturn, "gate-b-po", "IsSOTrx", "N", "MovementType", "V-")));
            assertEquals(NativeOperation.VENDOR_INVOICE, resolver.classify(
                    record("C_Invoice", invoice, "gate-b-po", "IsSOTrx", "N", "C_DocTypeTarget_ID", "202")).operationClass());
            assertNull(resolver.classify(record("C_Invoice", creditMemo, "gate-b-po", "IsSOTrx", "N",
                    "C_DocTypeTarget_ID", "203")), "an AP credit memo has no class");
            // A line is its stored header's class.
            assertEquals(NativeOperation.MATERIAL_RECEIPT, resolver.classify(record("M_InOutLine", 0, "gate-b-po",
                    "M_InOut_ID", String.valueOf(receipt))).operationClass());
            assertNull(resolver.classify(record("M_InOutLine", 0, "gate-b-po", "M_InOut_ID", String.valueOf(vendorReturn))));
            c.rollback();
        }
    }

    @Test
    void purchaseCompletionNeedsItsOwnClassAndNeverTheSalesOne() throws Exception {
        int order;
        try (Connection c = transaction()) {
            order = insertPurchase(c, "c_order", "", "");
            c.commit();
        }
        // A sales-order decision (a forged or reused class) cannot complete a purchase order.
        try (Connection c = transaction()) {
            attribute(c, new NativeOperation(NativeOperation.SALES_ORDER, "C_Order", order,
                    record("C_Order", order, "gate-b-po2", "IsSOTrx", "N")));
            sql(c, "UPDATE adempiere.c_order SET docstatus = 'CO' WHERE c_order_id = " + order);
            denied(c);
        }
        // Its own class completes it, and the JVM reuses that decision only for that class.
        try (Connection c = transaction()) {
            NativeOperation own = new NativeOperation(NativeOperation.PURCHASE_ORDER, "C_Order", order,
                    record("C_Order", order, "gate-b-po2", "IsSOTrx", "N"));
            attribute(c, own);
            NativeFinanceAttribution attribution = new NativeFinanceAttribution(trx -> c);
            assertTrue(attribution.hasCurrent(own));
            assertFalse(attribution.hasCurrent(new NativeOperation(NativeOperation.SALES_ORDER, "C_Order", order,
                    own.record())), "a decision is reused only for exactly its class");
            sql(c, "UPDATE adempiere.c_order SET docstatus = 'CO' WHERE c_order_id = " + order);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.c_order WHERE docstatus = 'CO' AND c_order_id = " + order));
    }

    @Test
    void paymentSelectionIsNeverAGovernedPathAndOutboundPaymentsCannotTurnOnline() throws Exception {
        int payment;
        try (Connection c = transaction()) {
            payment = insertDoc(c, "c_payment", "isreceipt", "N");
            c.commit();
        }
        // Bypass: direct SQL creating a payment selection for a placed client is refused outright.
        for (String table : new String[] {"c_payselection", "c_payselectionline", "c_payselectioncheck"}) {
            try (Connection c = transaction()) {
                SQLException e = assertThrows(SQLException.class, () -> sql(c, "INSERT INTO adempiere." + table
                        + " (" + table + "_id, ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", 11, 11)"));
                assertTrue(e.getMessage().contains("disbursement instructions are not governed"), e.getMessage());
            }
        }
        // A recorded outbound payment cannot be switched to online processing by direct SQL.
        try (Connection c = transaction()) {
            SQLException e = assertThrows(SQLException.class,
                    () -> sql(c, "UPDATE adempiere.c_payment SET isonline = 'Y' WHERE c_payment_id = " + payment));
            assertTrue(e.getMessage().contains("cannot become an online payment"), e.getMessage());
        }
        // Even a pre-existing selection row (unplaced history) strips the class: no recording, no completion.
        try (Connection c = transaction()) {
            sql(c, "ALTER TABLE adempiere.c_payselectioncheck DISABLE TRIGGER baobab_forbid_disbursement_instruction");
            sql(c, "INSERT INTO adempiere.c_payselectioncheck (c_payselectioncheck_id, ad_client_id, ad_org_id, c_payment_id) "
                    + "VALUES (" + IDS.incrementAndGet() + ", 11, 11, " + payment + ")");
            assertNull(storedClass_on(c, "C_Payment", payment), "a payment from a selection has no class");
            assertNull(new NativeOperationResolver(trx -> c).classify(
                    record("C_Payment", payment, "gate-b-ps", "IsReceipt", "N", "IsOnline", "N")));
            attribute(c, new NativeOperation(NativeOperation.VENDOR_PAYMENT, "C_Payment", payment,
                    record("C_Payment", payment, "gate-b-ps", "IsReceipt", "N", "IsOnline", "N")));
            sql(c, "UPDATE adempiere.c_payment SET docstatus = 'CO' WHERE c_payment_id = " + payment);
            denied(c);
        }
    }

    private static String storedClass_on(Connection c, String table, int id) throws SQLException {
        try (var s = c.prepareStatement("SELECT baobab_native.governed_class_of(?, ?)")) {
            s.setString(1, table);
            s.setInt(2, id);
            try (var r = s.executeQuery()) {
                r.next();
                return r.getString(1);
            }
        }
    }

    @Test
    void allocationsNeverNetPayablesAgainstReceivables() throws Exception {
        int vendorInvoice, vendorPayment, salesInvoice, allocation;
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API') ON CONFLICT DO NOTHING");
            vendorInvoice = vendorInvoice(c);
            c.commit();
        }
        ingestEvidence(vendorInvoice, "40.00", PARTNER, CURRENCY, "UGX");
        try (Connection c = transaction()) {
            vendorPayment = vendorPayment(c, vendorInvoice, "40.00", false);
            salesInvoice = insertDoc(c, "c_invoice", "issotrx", "Y");
            allocation = IDS.incrementAndGet();
            sql(c, "INSERT INTO adempiere.c_allocationhdr (c_allocationhdr_id, ad_client_id, ad_org_id) VALUES ("
                    + allocation + ", 11, 11)");
            c.commit();
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            // An empty draft header has no side yet; it carries no ledger effect.
            NativeRecord emptyHeader = new NativeRecord("C_AllocationHdr", CLIENT, ORG, allocation,
                    "model:TYPE_BEFORE_CHANGE", "gate-b-al", col -> "DocStatus".equals(col) ? "DR" : null);
            assertTrue(resolver.emptyDraftAllocation(emptyHeader));
            assertFalse(resolver.emptyDraftAllocation(new NativeRecord("C_AllocationHdr", CLIENT, ORG, allocation,
                    "document:TIMING_BEFORE_COMPLETE", "gate-b-al", col -> "DocStatus".equals(col) ? "DR" : null)),
                    "a document action is never an empty draft save");
            assertNull(resolver.classify(emptyHeader), "an empty allocation has no class");
            NativeRecord payablesLine = record("C_AllocationLine", 0, "gate-b-al", "C_AllocationHdr_ID",
                    String.valueOf(allocation), "C_Invoice_ID", String.valueOf(vendorInvoice),
                    "C_Payment_ID", String.valueOf(vendorPayment));
            assertEquals(NativeOperation.PAYABLES_ALLOCATION, resolver.classify(payablesLine).operationClass());
            assertNull(resolver.classify(record("C_AllocationLine", 0, "gate-b-al", "C_AllocationHdr_ID",
                    String.valueOf(allocation), "C_Invoice_ID", String.valueOf(salesInvoice),
                    "C_Payment_ID", String.valueOf(vendorPayment))), "a line joining both sides has no class");
            attribute(c, resolver.classify(payablesLine));
            sql(c, "INSERT INTO adempiere.c_allocationline (c_allocationline_id, c_allocationhdr_id, c_invoice_id, "
                    + "c_payment_id, ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", " + allocation + ", "
                    + vendorInvoice + ", " + vendorPayment + ", 11, 11)");
            assertEquals(NativeOperation.PAYABLES_ALLOCATION, storedClass_on(c, "C_AllocationHdr", allocation));
            // Once payables, a sales line can never join it.
            assertNull(resolver.classify(record("C_AllocationLine", 0, "gate-b-al", "C_AllocationHdr_ID",
                    String.valueOf(allocation), "C_Invoice_ID", String.valueOf(salesInvoice))));
            sql(c, "UPDATE adempiere.c_allocationhdr SET docstatus = 'CO' WHERE c_allocationhdr_id = " + allocation);
            c.commit();
        }
        // Bypass: direct SQL adding a sales line to the completed payables allocation is refused at COMMIT.
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_allocationline (c_allocationline_id, c_allocationhdr_id, c_invoice_id, "
                    + "ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", " + allocation + ", "
                    + salesInvoice + ", 11, 11)");
            denied(c);
        }
        assertEquals(NativeOperation.PAYABLES_ALLOCATION, storedClass("C_AllocationHdr", allocation));
    }

    @Test
    void matchingRowsAreFencedThroughTheirOneRootDocument() throws Exception {
        int receipt, receiptLine, invoice, invoiceLine;
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API') ON CONFLICT DO NOTHING");
            receipt = insertPurchase(c, "m_inout", ", movementtype", ", 'V+'");
            receiptLine = IDS.incrementAndGet();
            sql(c, "INSERT INTO adempiere.m_inoutline (m_inoutline_id, m_inout_id, ad_client_id, ad_org_id) VALUES ("
                    + receiptLine + ", " + receipt + ", 11, 11)");
            invoice = insertPurchase(c, "c_invoice", ", c_doctypetarget_id, c_doctype_id", ", 202, 0");
            invoiceLine = IDS.incrementAndGet();
            sql(c, "INSERT INTO adempiere.c_invoiceline (c_invoiceline_id, c_invoice_id, ad_client_id, ad_org_id) VALUES ("
                    + invoiceLine + ", " + invoice + ", 11, 11)");
            c.commit();
        }
        int matchPo = IDS.incrementAndGet();
        int matchInv = IDS.incrementAndGet();
        // Bypass: direct SQL matching without the root's authority in this transaction.
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.m_matchpo (m_matchpo_id, ad_client_id, ad_org_id, m_inoutline_id) VALUES ("
                    + matchPo + ", 11, 11, " + receiptLine + ")");
            denied(c);
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            NativeOperation po = resolver.classify(new NativeRecord("M_MatchPO", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW",
                    "gate-b-mt", col -> "M_InOutLine_ID".equals(col) ? receiptLine : null));
            assertEquals(NativeOperation.MATERIAL_RECEIPT, po.operationClass());
            assertEquals(receipt, po.sourceRecordId());
            NativeOperation inv = resolver.classify(new NativeRecord("M_MatchInv", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW",
                    "gate-b-mt", col -> switch (col) {
                        case "M_InOutLine_ID" -> receiptLine; case "C_InvoiceLine_ID" -> invoiceLine; default -> null; }));
            assertEquals(NativeOperation.VENDOR_INVOICE, inv.operationClass(), "an invoice match roots at its invoice");
            assertEquals(invoice, inv.sourceRecordId());
            attribute(c, po);
            attribute(c, inv);
            sql(c, "INSERT INTO adempiere.m_matchpo (m_matchpo_id, ad_client_id, ad_org_id, m_inoutline_id) VALUES ("
                    + matchPo + ", 11, 11, " + receiptLine + ")");
            sql(c, "INSERT INTO adempiere.m_matchinv (m_matchinv_id, ad_client_id, ad_org_id, m_inoutline_id, "
                    + "c_invoiceline_id) VALUES (" + matchInv + ", 11, 11, " + receiptLine + ", " + invoiceLine + ")");
            // The match's ledger rows are attributed through the same root.
            assertEquals(NativeOperation.VENDOR_INVOICE, resolver.classify(new NativeRecord("Fact_Acct", CLIENT, ORG, 0,
                    "model:TYPE_BEFORE_NEW", "gate-b-mt", col -> switch (col) {
                        case "AD_Table_ID" -> 472; case "Record_ID" -> matchInv; default -> null; })).operationClass());
            sql(c, "INSERT INTO adempiere.fact_acct (fact_acct_id, ad_client_id, ad_org_id, ad_table_id, record_id, "
                    + "c_period_id, amtacctdr) VALUES (" + IDS.incrementAndGet() + ", 11, 11, 472, " + matchInv + ", 301, 10)");
            c.commit();
        }
        // Bypass: deleting a match (unmatching) without the root's authority is refused at COMMIT.
        try (Connection c = transaction()) {
            sql(c, "DELETE FROM adempiere.m_matchinv WHERE m_matchinv_id = " + matchInv);
            denied(c);
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.m_matchinv WHERE m_matchinv_id = " + matchInv));
    }

    // --- ERP-A review fixes (ERP #100): client binding, match repointing, selection moves, last-line deletion ---

    /** An UNPLACED second client: iDempiere ids are global, so its documents are reachable by id. */
    private static int otherClientDoc(Connection c, String relation, String columns, String values) throws SQLException {
        sql(c, "INSERT INTO adempiere.ad_client VALUES (12, 'Y') ON CONFLICT DO NOTHING");
        int id = IDS.incrementAndGet();
        sql(c, "INSERT INTO adempiere." + relation + " (" + relation + "_id, ad_client_id, ad_org_id" + columns
                + ") VALUES (" + id + ", 12, 12" + values + ")");
        return id;
    }

    private static int emptyAllocation(Connection c) throws Exception {
        int allocation = IDS.incrementAndGet();
        sql(c, "INSERT INTO adempiere.c_allocationhdr (c_allocationhdr_id, ad_client_id, ad_org_id) VALUES ("
                + allocation + ", 11, 11)");
        return allocation;
    }

    @Test
    void allocationsNeverJoinAnotherClientsDocuments() throws Exception {
        int foreignInvoice, foreignPayment, allocation;
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API') ON CONFLICT DO NOTHING");
            foreignInvoice = otherClientDoc(c, "c_invoice", ", issotrx, c_doctypetarget_id, c_doctype_id", ", 'N', 202, 0");
            foreignPayment = otherClientDoc(c, "c_payment", ", isreceipt", ", 'N'");
            allocation = emptyAllocation(c);
            c.commit();
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            assertNull(resolver.classify(record("C_AllocationLine", 0, "gate-b-xc", "C_AllocationHdr_ID",
                    String.valueOf(allocation), "C_Invoice_ID", String.valueOf(foreignInvoice),
                    "C_Payment_ID", String.valueOf(foreignPayment))), "another client's documents have no side");
            // Bypass: even with a payables attribution, direct SQL joining them is refused at COMMIT.
            attribute(c, new NativeOperation(NativeOperation.PAYABLES_ALLOCATION, "C_AllocationHdr", allocation,
                    record("C_AllocationHdr", allocation, "gate-b-xc")));
            sql(c, "INSERT INTO adempiere.c_allocationline (c_allocationline_id, c_allocationhdr_id, c_invoice_id, "
                    + "c_payment_id, ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", " + allocation + ", "
                    + foreignInvoice + ", " + foreignPayment + ", 11, 11)");
            assertNull(storedClass_on(c, "C_AllocationHdr", allocation));
            denied(c);
        }
    }

    @Test
    void aMatchCannotBeRepointedWithoutBothRootsAuthority() throws Exception {
        int receiptA, lineA, receiptB, lineB, match;
        try (Connection c = transaction()) {
            receiptA = insertPurchase(c, "m_inout", ", movementtype", ", 'V+'");
            lineA = IDS.incrementAndGet();
            sql(c, "INSERT INTO adempiere.m_inoutline (m_inoutline_id, m_inout_id, ad_client_id, ad_org_id) VALUES ("
                    + lineA + ", " + receiptA + ", 11, 11)");
            receiptB = insertPurchase(c, "m_inout", ", movementtype", ", 'V+'");
            lineB = IDS.incrementAndGet();
            sql(c, "INSERT INTO adempiere.m_inoutline (m_inoutline_id, m_inout_id, ad_client_id, ad_org_id) VALUES ("
                    + lineB + ", " + receiptB + ", 11, 11)");
            c.commit();
        }
        match = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            attribute(c, new NativeOperation(NativeOperation.MATERIAL_RECEIPT, "M_InOut", receiptA,
                    record("M_InOut", receiptA, "gate-b-rp")));
            sql(c, "INSERT INTO adempiere.m_matchpo (m_matchpo_id, ad_client_id, ad_org_id, m_inoutline_id) VALUES ("
                    + match + ", 11, 11, " + lineA + ")");
            c.commit();
        }
        // The JVM refuses to re-point a stored match to another root.
        try (Connection c = transaction()) {
            assertNull(new NativeOperationResolver(trx -> c).classify(new NativeRecord("M_MatchPO", CLIENT, ORG, match,
                    "model:TYPE_BEFORE_CHANGE", "gate-b-rp", col -> "M_InOutLine_ID".equals(col) ? lineB : null)));
            c.rollback();
        }
        // Bypass: direct SQL re-pointing with only the NEW root's authority is refused at COMMIT.
        try (Connection c = transaction()) {
            attribute(c, new NativeOperation(NativeOperation.MATERIAL_RECEIPT, "M_InOut", receiptB,
                    record("M_InOut", receiptB, "gate-b-rp")));
            sql(c, "UPDATE adempiere.m_matchpo SET m_inoutline_id = " + lineB + " WHERE m_matchpo_id = " + match);
            denied(c);
        }
        // With BOTH roots' authority the change commits.
        try (Connection c = transaction()) {
            attribute(c, new NativeOperation(NativeOperation.MATERIAL_RECEIPT, "M_InOut", receiptA,
                    record("M_InOut", receiptA, "gate-b-rp")));
            attribute(c, new NativeOperation(NativeOperation.MATERIAL_RECEIPT, "M_InOut", receiptB,
                    record("M_InOut", receiptB, "gate-b-rp")));
            sql(c, "UPDATE adempiere.m_matchpo SET m_inoutline_id = " + lineB + " WHERE m_matchpo_id = " + match);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.m_matchpo WHERE m_inoutline_id = " + lineB
                + " AND m_matchpo_id = " + match));
    }

    @Test
    void aPaymentSelectionCanNeverMoveIntoOrOutOfAPlacedClient() throws Exception {
        int unplaced;
        int placed = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            unplaced = otherClientDoc(c, "c_payselection", "", "");
            c.commit();
        }
        try (Connection c = transaction()) {
            SQLException e = assertThrows(SQLException.class, () -> sql(c,
                    "UPDATE adempiere.c_payselection SET ad_client_id = 11, ad_org_id = 11 WHERE c_payselection_id = " + unplaced));
            assertTrue(e.getMessage().contains("disbursement instructions are not governed"), e.getMessage());
        }
        try (Connection c = transaction()) {
            // A placed client's pre-existing selection (history created before placement).
            sql(c, "ALTER TABLE adempiere.c_payselection DISABLE TRIGGER baobab_forbid_disbursement_instruction");
            sql(c, "INSERT INTO adempiere.c_payselection (c_payselection_id, ad_client_id, ad_org_id) VALUES ("
                    + placed + ", 11, 11)");
            sql(c, "ALTER TABLE adempiere.c_payselection ENABLE TRIGGER baobab_forbid_disbursement_instruction");
            SQLException e = assertThrows(SQLException.class, () -> sql(c,
                    "UPDATE adempiere.c_payselection SET ad_client_id = 12, ad_org_id = 12 WHERE c_payselection_id = " + placed));
            assertTrue(e.getMessage().contains("disbursement instructions are not governed"), e.getMessage());
        }
    }

    @Test
    void theLastAllocationLineIsDeletedOnlyWithItsOwnSidesAuthority() throws Exception {
        int invoice, payment, allocation, line;
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API') ON CONFLICT DO NOTHING");
            invoice = vendorInvoice(c);
            c.commit();
        }
        ingestEvidence(invoice, "41.00", PARTNER, CURRENCY, "UGX");
        try (Connection c = transaction()) {
            payment = vendorPayment(c, invoice, "41.00", false);
            allocation = emptyAllocation(c);
            c.commit();
        }
        line = IDS.incrementAndGet();
        NativeOperation payables = new NativeOperation(NativeOperation.PAYABLES_ALLOCATION, "C_AllocationHdr",
                allocation, record("C_AllocationHdr", allocation, "gate-b-dl"));
        try (Connection c = transaction()) {
            attribute(c, payables);
            sql(c, "INSERT INTO adempiere.c_allocationline (c_allocationline_id, c_allocationhdr_id, c_invoice_id, "
                    + "c_payment_id, ad_client_id, ad_org_id) VALUES (" + line + ", " + allocation + ", " + invoice + ", "
                    + payment + ", 11, 11)");
            c.commit();
        }
        // Without authority the deletion is refused at COMMIT.
        try (Connection c = transaction()) {
            sql(c, "DELETE FROM adempiere.c_allocationline WHERE c_allocationline_id = " + line);
            denied(c);
        }
        // A sales decision is not the deleted line's side.
        try (Connection c = transaction()) {
            attribute(c, new NativeOperation(NativeOperation.ALLOCATION, "C_AllocationHdr", allocation,
                    record("C_AllocationHdr", allocation, "gate-b-dl")));
            sql(c, "DELETE FROM adempiere.c_allocationline WHERE c_allocationline_id = " + line);
            denied(c);
        }
        // With its own side's authority the final line is deleted, leaving an empty allocation.
        try (Connection c = transaction()) {
            attribute(c, payables);
            sql(c, "DELETE FROM adempiere.c_allocationline WHERE c_allocationline_id = " + line);
            c.commit();
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.c_allocationline WHERE c_allocationhdr_id = " + allocation));
    }

    // --- ERP-A purchase costing (N0007): an order-line cost detail derives from its one authorised receipt ---

    /** A vendor receipt with one line, matched by M_MatchPO to a purchase-order line, all in client 11. */
    private static int[] matchedReceipt(Connection c, int orderLine) throws Exception {
        int receipt = insertPurchase(c, "m_inout", ", movementtype", ", 'V+'");
        int line = IDS.incrementAndGet();
        sql(c, "INSERT INTO adempiere.m_inoutline (m_inoutline_id, m_inout_id, ad_client_id, ad_org_id) VALUES ("
                + line + ", " + receipt + ", 11, 11)");
        attribute(c, new NativeOperation(NativeOperation.MATERIAL_RECEIPT, "M_InOut", receipt,
                record("M_InOut", receipt, "gate-b-pc")));
        sql(c, "INSERT INTO adempiere.m_matchpo (m_matchpo_id, ad_client_id, ad_org_id, c_orderline_id, m_inoutline_id) "
                + "VALUES (" + IDS.incrementAndGet() + ", 11, 11, " + orderLine + ", " + line + ")");
        return new int[] {receipt, line};
    }

    private static NativeRecord orderLineCost(int orderLine, String extraColumn, int extraValue) {
        return new NativeRecord("M_CostDetail", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW", "gate-b-pc", col -> switch (col) {
            case "C_OrderLine_ID" -> orderLine;
            case "IsSOTrx" -> "N";
            case "M_Product_ID" -> 501;
            case "C_AcctSchema_ID" -> 101;
            case "M_CostElement_ID" -> 601;
            default -> col.equals(extraColumn) ? extraValue : null;
        });
    }

    private static void writeOrderLineCost(Connection c, int orderLine) throws SQLException {
        sql(c, "INSERT INTO adempiere.m_costdetail (m_costdetail_id, ad_client_id, ad_org_id, m_product_id, "
                + "c_acctschema_id, m_costelement_id, c_orderline_id, issotrx) VALUES (" + IDS.incrementAndGet()
                + ", 11, 11, 501, 101, 601, " + orderLine + ", 'N')");
    }

    @Test
    void purchaseOrderLineCostingDerivesFromItsOneAuthorisedReceipt() throws Exception {
        int orderLine = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            int receipt = matchedReceipt(c, orderLine)[0];
            NativeConnections same = trx -> c;
            NativeOperation root = new NativeOperationResolver(same).classify(orderLineCost(orderLine, null, 0));
            assertNotNull(root, "an order-line cost detail roots at its matched, authorised receipt");
            assertEquals(NativeOperation.MATERIAL_RECEIPT, root.operationClass());
            assertEquals(receipt, root.sourceRecordId());
            new NativeDerivedWrites(same).appendCostDetail(root);
            writeOrderLineCost(c, orderLine);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.m_costdetail WHERE c_orderline_id = " + orderLine));
    }

    @Test
    void purchaseCostingWithoutASingleAuthorisedReceiptIsDenied() throws Exception {
        // No receipt authority in this transaction: no root; direct SQL refused at COMMIT.
        int orderLine = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            int receipt = insertPurchase(c, "m_inout", ", movementtype", ", 'V+'");
            int line = IDS.incrementAndGet();
            sql(c, "INSERT INTO adempiere.m_inoutline (m_inoutline_id, m_inout_id, ad_client_id, ad_org_id) VALUES ("
                    + line + ", " + receipt + ", 11, 11)");
            c.commit();
        }
        try (Connection c = transaction()) {
            assertNull(new NativeOperationResolver(trx -> c).classify(orderLineCost(orderLine, null, 0)));
            writeOrderLineCost(c, orderLine);
            denied(c);
        }
        // Two authorised receipts matched to the same order line: ambiguous, no root.
        int shared = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            matchedReceipt(c, shared);
            matchedReceipt(c, shared);
            assertNull(new NativeOperationResolver(trx -> c).classify(orderLineCost(shared, null, 0)),
                    "several candidate receipts are ambiguous");
            c.rollback();
        }
        // Any second cost source (an invoice line: price variance) is not this derived write.
        int mixed = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            matchedReceipt(c, mixed);
            assertNull(new NativeOperationResolver(trx -> c).classify(
                    orderLineCost(mixed, "C_InvoiceLine_ID", IDS.incrementAndGet())));
            c.rollback();
        }
    }

    // --- ERP-A invoice-match costing (N0007): an invoice-line cost detail derives from its matched vendor invoice ---

    /** An AP document of the given type with one line in client 11, optionally matched by an M_MatchInv. */
    private static int[] apInvoiceLine(Connection c, int docType, boolean matched) throws Exception {
        sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API'), (203, 'APC') ON CONFLICT DO NOTHING");
        int invoice = insertPurchase(c, "c_invoice", ", c_doctypetarget_id, c_doctype_id", ", " + docType + ", 0");
        int line = IDS.incrementAndGet();
        sql(c, "INSERT INTO adempiere.c_invoiceline (c_invoiceline_id, c_invoice_id, ad_client_id, ad_org_id) VALUES ("
                + line + ", " + invoice + ", 11, 11)");
        if (matched) {
            sql(c, "INSERT INTO adempiere.m_matchinv (m_matchinv_id, ad_client_id, ad_org_id, c_invoiceline_id) VALUES ("
                    + IDS.incrementAndGet() + ", 11, 11, " + line + ")");
        }
        return new int[] {invoice, line};
    }

    private static NativeRecord invoiceLineCost(int invoiceLine, String isSOTrx, String extraColumn, int extraValue) {
        return new NativeRecord("M_CostDetail", CLIENT, ORG, 0, "model:TYPE_BEFORE_NEW", "gate-b-ic", col -> switch (col) {
            case "C_InvoiceLine_ID" -> invoiceLine;
            case "IsSOTrx" -> isSOTrx;
            case "M_Product_ID" -> 501;
            case "C_AcctSchema_ID" -> 101;
            default -> col.equals(extraColumn) ? extraValue : null;
        });
    }

    private static void writeInvoiceLineCost(Connection c, int invoiceLine) throws SQLException {
        sql(c, "INSERT INTO adempiere.m_costdetail (m_costdetail_id, ad_client_id, ad_org_id, m_product_id, "
                + "c_acctschema_id, c_invoiceline_id, issotrx) VALUES (" + IDS.incrementAndGet()
                + ", 11, 11, 501, 101, " + invoiceLine + ", 'N')");
    }

    @Test
    void invoiceMatchCostingDerivesFromItsOwnMatchedVendorInvoice() throws Exception {
        int line;
        try (Connection c = transaction()) {
            int[] invoice = apInvoiceLine(c, 202, true);
            line = invoice[1];
            NativeConnections same = trx -> c;
            NativeOperation root = new NativeOperationResolver(same).classify(invoiceLineCost(line, "N", null, 0));
            assertNotNull(root, "a matched vendor-invoice line's cost detail roots at its own vendor invoice");
            assertEquals(NativeOperation.VENDOR_INVOICE, root.operationClass());
            assertEquals("C_Invoice", root.sourceTable());
            assertEquals(invoice[0], root.sourceRecordId());
            attribute(c, root);
            new NativeDerivedWrites(same).appendCostDetail(root);
            writeInvoiceLineCost(c, line);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM adempiere.m_costdetail WHERE c_invoiceline_id = " + line));
    }

    @Test
    void invoiceLineCostingWithoutAMatchedVendorInvoiceIsDenied() throws Exception {
        // Unmatched line: no root, and with the invoice's authority alone the detail is refused at COMMIT.
        try (Connection c = transaction()) {
            int[] invoice = apInvoiceLine(c, 202, false);
            assertNull(new NativeOperationResolver(trx -> c).classify(invoiceLineCost(invoice[1], "N", null, 0)));
            attribute(c, new NativeOperation(NativeOperation.VENDOR_INVOICE, "C_Invoice", invoice[0],
                    record("C_Invoice", invoice[0], "gate-b-ic")));
            writeInvoiceLineCost(c, invoice[1]);
            denied(c);
        }
        // An AP credit memo is never a vendor invoice record, matched or not.
        try (Connection c = transaction()) {
            int[] memo = apInvoiceLine(c, 203, true);
            assertNull(new NativeOperationResolver(trx -> c).classify(invoiceLineCost(memo[1], "N", null, 0)));
            c.rollback();
        }
        // A sales-side detail, or a second cost source, is not this derived write.
        try (Connection c = transaction()) {
            int[] invoice = apInvoiceLine(c, 202, true);
            NativeOperationResolver resolver = new NativeOperationResolver(trx -> c);
            assertNull(resolver.classify(invoiceLineCost(invoice[1], "Y", null, 0)));
            assertNull(resolver.classify(invoiceLineCost(invoice[1], "N", "M_InOutLine_ID", IDS.incrementAndGet())));
            assertNull(resolver.classify(invoiceLineCost(invoice[1], "N", "PP_Cost_Collector_ID", IDS.incrementAndGet())));
            c.rollback();
        }
        // A receipt's derived attribution never covers an invoice-line detail.
        int orderLine = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            int receipt = matchedReceipt(c, orderLine)[0];
            NativeConnections same = trx -> c;
            new NativeDerivedWrites(same).appendCostDetail(new NativeOperation(NativeOperation.MATERIAL_RECEIPT,
                    "M_InOut", receipt, orderLineCost(orderLine, null, 0)));
            int[] invoice = apInvoiceLine(c, 202, true);
            attribute(c, new NativeOperation(NativeOperation.VENDOR_INVOICE, "C_Invoice", invoice[0],
                    record("C_Invoice", invoice[0], "gate-b-ic")));
            writeInvoiceLineCost(c, invoice[1]);
            denied(c);
        }
    }

    // --- P0-04B ERP-B (N0008, ADR-SHARED-038): payment-execution provenance and deny-by-name ---

    private static final int PARTNER = 701;
    private static final int CURRENCY = 300;
    private static final String INGEST = "gateb_evidence_ingest";

    /** A vendor invoice (base type API) of PARTNER in CURRENCY, client 11. */
    private static int vendorInvoice(Connection c) throws SQLException {
        sql(c, "INSERT INTO adempiere.c_doctype VALUES (202, 'API') ON CONFLICT DO NOTHING");
        return insertPurchase(c, "c_invoice", ", c_doctypetarget_id, c_doctype_id, c_bpartner_id, c_currency_id",
                ", 202, 0, " + PARTNER + ", " + CURRENCY);
    }

    /** A recorded outbound payment of PARTNER; withInvoice names the obligation on the payment itself. */
    private static int vendorPayment(Connection c, int invoice, String amount, boolean withInvoice) throws SQLException {
        int id = IDS.incrementAndGet();
        sql(c, "INSERT INTO adempiere.c_payment (c_payment_id, ad_client_id, ad_org_id, c_doctype_id, isreceipt, "
                + "c_bpartner_id, c_currency_id, payamt, c_invoice_id) VALUES (" + id + ", 11, 11, 201, 'N', " + PARTNER
                + ", " + CURRENCY + ", " + amount + ", " + (withInvoice ? invoice : "NULL") + ")");
        return id;
    }

    /** The payment as the JVM veto sees it being saved: its own values, never a caller's. */
    private static NativeRecord payment(int id, int invoice, String amount, String... more) {
        String[] values = {"IsReceipt", "N", "C_BPartner_ID", String.valueOf(PARTNER),
                "C_Currency_ID", String.valueOf(CURRENCY), "PayAmt", amount, "C_Invoice_ID", String.valueOf(invoice)};
        String[] all = java.util.Arrays.copyOf(values, values.length + more.length);
        System.arraycopy(more, 0, all, values.length, more.length);
        return record("C_Payment", id, "gate-b-pee", all);
    }

    /** The ingest role: a non-superuser member of baobab_payment_evidence_ingest. */
    private static void ingestRole(Connection c) throws SQLException {
        sql(c, "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '" + INGEST + "') THEN "
                + "CREATE ROLE " + INGEST + " NOLOGIN NOSUPERUSER IN ROLE baobab_payment_evidence_ingest; END IF; END $$");
    }

    private static String evidenceInsert(int invoice, String amount, int partner, int currency, String iso,
                                         String legalEntity) {
        return "INSERT INTO baobab_native.payment_execution_evidence (evidence_id, execution_authority, placement_id, "
                + "placement_version, responsible_legal_entity_id, ad_client_id, ad_org_id, payee_reference, c_bpartner_id, "
                + "obligation_reference, c_invoice_id, currency, c_currency_id, amount, executed_at, verified_at, "
                + "verified_by, evidence_references) VALUES ('" + UUID.randomUUID() + "', 'SYNTHETIC_ENGINE_LOCAL', '"
                + placementId + "', 1, '" + legalEntity + "', 11, 11, 'erp:bpartner/" + partner + "', " + partner
                + ", 'erp:vendor-invoice/" + invoice + "', " + invoice + ", '" + iso + "', " + currency + ", " + amount
                + ", now() - interval '2 minutes', now() - interval '1 minute', 'Synthetic Payment Verifier', "
                + "ARRAY['synthetic:gate-b/payment-execution'])";
    }

    /** Independently verified execution evidence, written by the ingest role in its own transaction. */
    private static void ingestEvidence(int invoice, String amount, int partner, int currency, String iso)
            throws SQLException {
        try (Connection c = transaction()) {
            ingestRole(c);
            sql(c, "SET LOCAL ROLE " + INGEST);
            sql(c, evidenceInsert(invoice, amount, partner, currency, iso, LE));
            c.commit();
        }
    }

    private static void refused(String statement, String message, boolean asIngest) throws SQLException {
        try (Connection c = transaction()) {
            ingestRole(c);
            if (asIngest) sql(c, "SET LOCAL ROLE " + INGEST);
            SQLException e = assertThrows(SQLException.class, () -> sql(c, statement));
            assertTrue(e.getMessage().contains(message), e.getMessage());
        }
    }

    @Test
    void vendorPaymentRecordingNeedsItsOwnBoundExecutionEvidence() throws Exception {
        int invoice;
        try (Connection c = transaction()) {
            invoice = vendorInvoice(c);
            c.commit();
        }
        // No evidence: no class, at the JVM and in the database; a forged attribution cannot complete it.
        int bare;
        try (Connection c = transaction()) {
            assertNull(new NativeOperationResolver(trx -> c).classify(payment(0, invoice, "300.00", "IsOnline", "N")),
                    "an outbound payment without execution evidence has no class");
            bare = vendorPayment(c, invoice, "300.00", true);
            assertNull(storedClass_on(c, "C_Payment", bare));
            attribute(c, new NativeOperation(NativeOperation.VENDOR_PAYMENT, "C_Payment", bare,
                    payment(bare, invoice, "300.00", "IsOnline", "N")));
            sql(c, "UPDATE adempiere.c_payment SET docstatus = 'CO' WHERE c_payment_id = " + bare);
            denied(c);
        }
        // Evidence for other values never matches: amount, payee, obligation or currency.
        int otherInvoice;
        try (Connection c = transaction()) {
            otherInvoice = vendorInvoice(c);
            c.commit();
        }
        ingestEvidence(otherInvoice, "300.00", PARTNER, CURRENCY, "UGX");
        ingestEvidence(invoice, "299.99", PARTNER, CURRENCY, "UGX");
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            assertNull(resolver.classify(payment(0, invoice, "300.00", "IsOnline", "N")), "another obligation");
            assertNull(resolver.classify(record("C_Payment", 0, "gate-b-pee", "IsReceipt", "N", "IsOnline", "N",
                    "C_BPartner_ID", "702", "C_Currency_ID", String.valueOf(CURRENCY), "PayAmt", "299.99",
                    "C_Invoice_ID", String.valueOf(invoice))), "another payee");
            assertNull(resolver.classify(record("C_Payment", 0, "gate-b-pee", "IsReceipt", "N", "IsOnline", "N",
                    "C_BPartner_ID", String.valueOf(PARTNER), "C_Currency_ID", "100", "PayAmt", "299.99",
                    "C_Invoice_ID", String.valueOf(invoice))), "another currency");
            assertNull(resolver.classify(payment(0, invoice, "0", "IsOnline", "N")), "no amount");
        }
        // Matching evidence: the payment is classified, bound on insert, and completes once attributed.
        ingestEvidence(invoice, "300.00", PARTNER, CURRENCY, "UGX");
        int paid;
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            assertEquals(NativeOperation.VENDOR_PAYMENT,
                    resolver.classify(payment(0, invoice, "300.00", "IsOnline", "N")).operationClass());
            paid = vendorPayment(c, invoice, "300.00", true);
            assertEquals(NativeOperation.VENDOR_PAYMENT, storedClass_on(c, "C_Payment", paid));
            attribute(c, resolver.classify(payment(paid, invoice, "300.00", "IsOnline", "N")));
            sql(c, "UPDATE adempiere.c_payment SET docstatus = 'CO' WHERE c_payment_id = " + paid);
            c.commit();
        }
        assertEquals(1, count("SELECT count(*) FROM baobab_native.payment_execution_binding WHERE c_payment_id = " + paid));
        // The evidence is consumed: an identical second payment has no class and binds nothing.
        try (Connection c = transaction()) {
            assertNull(new NativeOperationResolver(trx -> c).classify(payment(0, invoice, "300.00", "IsOnline", "N")),
                    "evidence binds one payment only");
            int again = vendorPayment(c, invoice, "300.00", true);
            assertNull(storedClass_on(c, "C_Payment", again));
            c.rollback();
        }
        // A bound payment whose values drift from its evidence loses its class (direct SQL included).
        try (Connection c = transaction()) {
            sql(c, "UPDATE adempiere.c_payment SET payamt = 310 WHERE c_payment_id = " + paid);
            assertNull(storedClass_on(c, "C_Payment", paid), "a changed amount no longer matches the evidence");
            assertNull(new NativeOperationResolver(trx -> c).classify(payment(paid, invoice, "310.00", "IsOnline", "N")));
            c.rollback();
        }
        // Ambiguity denies: two unbound records for the same values bind neither.
        ingestEvidence(invoice, "77.00", PARTNER, CURRENCY, "UGX");
        ingestEvidence(invoice, "77.00", PARTNER, CURRENCY, "UGX");
        try (Connection c = transaction()) {
            assertNull(new NativeOperationResolver(trx -> c).classify(payment(0, invoice, "77.00", "IsOnline", "N")),
                    "ambiguous evidence denies");
            int ambiguous = vendorPayment(c, invoice, "77.00", true);
            assertNull(storedClass_on(c, "C_Payment", ambiguous));
            c.rollback();
        }
    }

    @Test
    void executionEvidenceIsWrittenOnlyByTheIngestRoleAndNeverChanges() throws Exception {
        int invoice, salesInvoice;
        try (Connection c = transaction()) {
            invoice = vendorInvoice(c);
            salesInvoice = insertDoc(c, "c_invoice", "issotrx", "Y");
            sql(c, "UPDATE adempiere.c_invoice SET c_bpartner_id = " + PARTNER + ", c_currency_id = " + CURRENCY
                    + " WHERE c_invoice_id = " + salesInvoice);
            c.commit();
        }
        // A superuser (as iDempiere's runtime role is in the engine-local harness) is refused.
        refused(evidenceInsert(invoice, "10.00", PARTNER, CURRENCY, "UGX", LE), "written only by the ingest role", false);
        // Facts the evidence must agree with: legal entity, obligation class, payee and currency code.
        refused(evidenceInsert(invoice, "10.00", PARTNER, CURRENCY, "UGX", "SYNTHETIC-OTHER-LE"), "open placement", true);
        refused(evidenceInsert(salesInvoice, "10.00", PARTNER, CURRENCY, "UGX", LE), "not a vendor invoice", true);
        refused(evidenceInsert(invoice, "10.00", 702, CURRENCY, "UGX", LE), "not a vendor invoice", true);
        refused(evidenceInsert(invoice, "10.00", PARTNER, CURRENCY, "USD", LE), "currency code", true);
        refused(evidenceInsert(invoice, "0", PARTNER, CURRENCY, "UGX", LE), "check constraint", true);
        refused(evidenceInsert(invoice, "10.00", PARTNER, CURRENCY, "UGX", LE)
                .replace("'SYNTHETIC_ENGINE_LOCAL'", "'PAYMENTS_PAYOUT'"), "check constraint", true);
        // Append-only: neither evidence nor a binding is ever changed or removed.
        ingestEvidence(invoice, "10.00", PARTNER, CURRENCY, "UGX");
        int bound;
        try (Connection c = transaction()) {
            bound = vendorPayment(c, invoice, "10.00", true);
            c.commit();
        }
        for (String statement : new String[] {
                "UPDATE baobab_native.payment_execution_evidence SET amount = 11 WHERE c_invoice_id = " + invoice,
                "DELETE FROM baobab_native.payment_execution_evidence WHERE c_invoice_id = " + invoice,
                "UPDATE baobab_native.payment_execution_binding SET c_payment_id = c_payment_id + 1 WHERE c_payment_id = " + bound,
                "DELETE FROM baobab_native.payment_execution_binding WHERE c_payment_id = " + bound}) {
            refused(statement, "append-only", false);
        }
    }

    @Test
    void aVendorPaymentIsAllocatedOnlyToItsEvidenceObligation() throws Exception {
        int obligation, otherInvoice, pay, allocation;
        try (Connection c = transaction()) {
            obligation = vendorInvoice(c);
            otherInvoice = vendorInvoice(c);
            c.commit();
        }
        ingestEvidence(obligation, "55.00", PARTNER, CURRENCY, "UGX");
        try (Connection c = transaction()) {
            pay = vendorPayment(c, obligation, "55.00", false);
            allocation = emptyAllocation(c);
            c.commit();
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            assertEquals(NativeOperation.VENDOR_PAYMENT, storedClass_on(c, "C_Payment", pay));
            assertNull(resolver.classify(record("C_AllocationLine", 0, "gate-b-ob", "C_AllocationHdr_ID",
                    String.valueOf(allocation), "C_Invoice_ID", String.valueOf(otherInvoice),
                    "C_Payment_ID", String.valueOf(pay))), "another vendor invoice is not the evidence's obligation");
            assertNull(resolver.classify(record("C_AllocationLine", 0, "gate-b-ob", "C_AllocationHdr_ID",
                    String.valueOf(allocation), "C_Payment_ID", String.valueOf(pay))),
                    "a payment is never allocated on its own");
            assertEquals(NativeOperation.PAYABLES_ALLOCATION, resolver.classify(record("C_AllocationLine", 0, "gate-b-ob",
                    "C_AllocationHdr_ID", String.valueOf(allocation), "C_Invoice_ID", String.valueOf(obligation),
                    "C_Payment_ID", String.valueOf(pay))).operationClass());
            // Bypass: a direct SQL line to another invoice is refused at COMMIT even with payables authority.
            attribute(c, new NativeOperation(NativeOperation.PAYABLES_ALLOCATION, "C_AllocationHdr", allocation,
                    record("C_AllocationHdr", allocation, "gate-b-ob")));
            sql(c, "INSERT INTO adempiere.c_allocationline (c_allocationline_id, c_allocationhdr_id, c_invoice_id, "
                    + "c_payment_id, ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", " + allocation + ", "
                    + otherInvoice + ", " + pay + ", 11, 11)");
            sql(c, "UPDATE adempiere.c_allocationhdr SET docstatus = 'CO' WHERE c_allocationhdr_id = " + allocation);
            denied(c);
        }
    }

    @Test
    void uncataloguedFamiliesAreRefusedByNameInTheJvmAndInPostgres() throws Exception {
        String[][] families = {{"C_BankStatement", "c_bankstatement"}, {"C_BankStatementLine", "c_bankstatementline"},
                {"C_Cash", "c_cash"}, {"C_CashLine", "c_cashline"}, {"M_Inventory", "m_inventory"},
                {"M_InventoryLine", "m_inventoryline"}, {"M_Movement", "m_movement"}, {"M_MovementLine", "m_movementline"},
                {"M_Production", "m_production"}, {"M_ProductionLine", "m_productionline"},
                {"M_ProductionPlan", "m_productionplan"}, {"C_LandedCost", "c_landedcost"},
                {"C_LandedCostAllocation", "c_landedcostallocation"}};
        for (String[] family : families) {
            String table = family[0], relation = family[1];
            // JVM: the table is protected and no write to it has a class.
            assertTrue(NativeFinancePolicy.protectedTables().contains(table), table);
            try (Connection c = transaction()) {
                assertNull(new NativeOperationResolver(trx -> c).classify(new NativeRecord(table, CLIENT, ORG, 0,
                        "model:TYPE_BEFORE_NEW", "gate-b-dbn", col -> null)), table);
            }
            // PostgreSQL: refused for a placed client, whoever writes it.
            try (Connection c = transaction()) {
                SQLException e = assertThrows(SQLException.class, () -> sql(c, "INSERT INTO adempiere." + relation
                        + " (" + relation + "_id, ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", 11, 11)"));
                assertTrue(e.getMessage().contains("is not a catalogued operation family"), e.getMessage());
            }
            // An unplaced client is untouched, and its rows never move into a placed client.
            int unplaced;
            try (Connection c = transaction()) {
                unplaced = otherClientDoc(c, relation, "", "");
                c.commit();
            }
            try (Connection c = transaction()) {
                // (Bank statements and cash journals are provenance-governed headers too: N0002 may refuse first.)
                SQLException e = assertThrows(SQLException.class, () -> sql(c, "UPDATE adempiere." + relation
                        + " SET ad_client_id = 11, ad_org_id = 11 WHERE " + relation + "_id = " + unplaced));
                assertTrue(e.getMessage().contains("BAOBAB_NATIVE_FINANCE_DENIED"), e.getMessage());
            }
        }
        // A bank statement never mints a payment: the statement write fails the whole transaction,
        // including a receipt created and attributed in it, so nothing persists.
        int receipt = IDS.incrementAndGet();
        try (Connection c = transaction()) {
            sql(c, "INSERT INTO adempiere.c_payment (c_payment_id, ad_client_id, ad_org_id, c_doctype_id, isreceipt) "
                    + "VALUES (" + receipt + ", 11, 11, 201, 'Y')");
            attribute(c, new NativeOperation(NativeOperation.PAYMENT, "C_Payment", receipt,
                    record("C_Payment", receipt, "gate-b-bs", "IsReceipt", "Y")));
            assertThrows(SQLException.class, () -> sql(c, "INSERT INTO adempiere.c_bankstatementline "
                    + "(c_bankstatementline_id, ad_client_id, ad_org_id) VALUES (" + IDS.incrementAndGet() + ", 11, 11)"));
            // PostgreSQL answers COMMIT of the aborted transaction with a rollback.
            try { c.commit(); } catch (SQLException rolledBack) { /* either way nothing persists */ }
        }
        assertEquals(0, count("SELECT count(*) FROM adempiere.c_payment WHERE c_payment_id = " + receipt));
    }


    // DEV-09: real PostgreSQL/JDBC proof for two synthetic, distinct native
    // company/org pairs. This is not two provisioned iDempiere JVM companies.
    @Test
    void distinctNativeClientsHaveIsolatedDocumentsAndContext() throws Exception {
        int a = IDS.incrementAndGet(), b = IDS.incrementAndGet();
        try (Connection c = transaction(); Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.ad_client (ad_client_id) VALUES (31), (32)");
            s.execute("INSERT INTO adempiere.ad_org (ad_org_id, ad_client_id) VALUES (31, 31), (32, 32)");
            s.execute("""
                INSERT INTO baobab_native.native_placement
                  (placement_id, version, tenant_id, engine_instance_id, operating_organisation_id,
                   legal_entity_id, market, ad_client_id, ad_org_id, effective_from, approved_by,
                   checked_by, evidence_reference, erp_assignment_reference)
                VALUES
                  ('%s', 1, 'tn_deva31', 'ei_deva31', '29e7e63e-78c2-4d49-94b8-2c8951bb8001',
                   'LE-DEV09A', 'UG', 31, 31, now() - interval '1 hour',
                   'Company A Maker', 'Company A Checker', 'synthetic:dev09/a', 'synthetic:dev09/a'),
                  ('%s', 1, 'tn_devb32', 'ei_devb32', '29e7e63e-78c2-4d49-94b8-2c8951bb8002',
                   'LE-DEV09B', 'ZA', 32, 32, now() - interval '1 hour',
                   'Company B Maker', 'Company B Checker', 'synthetic:dev09/b', 'synthetic:dev09/b')
                """.formatted(UUID.randomUUID(), UUID.randomUUID()));
            s.execute("INSERT INTO adempiere.c_order (c_order_id, ad_client_id, ad_org_id) VALUES ("
                    + a + ", 31, 31), (" + b + ", 32, 32)");
            PlacementContextSource resolver = new PlacementContextSource(trx -> c);
            NativeOperation sourceA = new NativeOperation(NativeOperation.PURCHASE_ORDER, "C_Order", a,
                    new NativeRecord("C_Order", 31, 31, a, "model:TYPE_BEFORE_CHANGE", "dev09-a", col -> null));
            NativeOperation sourceB = new NativeOperation(NativeOperation.PURCHASE_ORDER, "C_Order", b,
                    new NativeRecord("C_Order", 32, 32, b, "model:TYPE_BEFORE_CHANGE", "dev09-b", col -> null));
            NativePlacement pa = resolver.currentPlacement(sourceA), pb = resolver.currentPlacement(sourceB);
            assertNotNull(pa);
            assertNotNull(pb);
            assertEquals("tn_deva31", pa.tenantId());
            assertEquals("LE-DEV09A", pa.legalEntityId());
            assertEquals("UG", pa.market());
            assertEquals("tn_devb32", pb.tenantId());
            assertEquals("LE-DEV09B", pb.legalEntityId());
            assertEquals("ZA", pb.market());
            assertNotEquals(pa.placementId(), pb.placementId());
            // A source document cannot be reassigned through a forged native
            // callback from another AD_Client or an altered header AD_Org.
            NativeOperation wrongClient = new NativeOperation(NativeOperation.PURCHASE_ORDER, "C_Order", a,
                    new NativeRecord("C_Order", 32, 32, a, "model:TYPE_BEFORE_CHANGE", "dev09-cross", col -> null));
            NativeOperation wrongOrg = new NativeOperation(NativeOperation.PURCHASE_ORDER, "C_Order", a,
                    new NativeRecord("C_Order", 31, 32, a, "model:TYPE_BEFORE_CHANGE", "dev09-cross", col -> null));
            assertNull(resolver.currentPlacement(wrongClient));
            assertNull(resolver.currentPlacement(wrongOrg));
            c.rollback();
        }
        assertEquals(0, count("SELECT count(*) FROM baobab_native.native_placement WHERE ad_client_id IN (31,32)"));
        assertEquals(0, count("SELECT count(*) FROM baobab_native.document_provenance WHERE record_id IN ("
                + a + "," + b + ")"));
    }

    @Test
    void placementCannotAssociateAnOrgOwnedByAnotherCompany() throws Exception {
        // Moving/deactivating an already governed AD_Org cannot invalidate
        // an open legal/tenant placement behind CP's back.
        try (Connection c = transaction(); Statement s = c.createStatement()) {
            SQLException inactive = assertThrows(SQLException.class, () ->
                    s.execute("UPDATE adempiere.ad_org SET isactive = 'N' WHERE ad_org_id = 11"));
            assertTrue(inactive.getMessage().contains("BAOBAB_NATIVE_FINANCE_DENIED"), inactive.getMessage());
            c.rollback();
        }
        try (Connection c = transaction(); Statement s = c.createStatement()) {
            s.execute("INSERT INTO adempiere.ad_client (ad_client_id) VALUES (41), (42)");
            s.execute("INSERT INTO adempiere.ad_org (ad_org_id, ad_client_id) VALUES (41, 41), (42, 42)");
            SQLException denied = assertThrows(SQLException.class, () -> s.execute("""
                INSERT INTO baobab_native.native_placement
                  (placement_id, version, tenant_id, engine_instance_id, operating_organisation_id,
                   legal_entity_id, market, ad_client_id, ad_org_id, effective_from, approved_by,
                   checked_by, evidence_reference, erp_assignment_reference)
                VALUES ('%s', 1, 'tn_devc41', 'ei_devc41', '29e7e63e-78c2-4d49-94b8-2c8951bb8003',
                        'LE-DEV09C', 'UG', 41, 42, now() - interval '1 hour',
                        'Company C Maker', 'Company C Checker', 'synthetic:dev09/c', 'synthetic:dev09/c')
                """.formatted(UUID.randomUUID())));
            assertTrue(denied.getMessage().contains("BAOBAB_NATIVE_FINANCE_DENIED"), denied.getMessage());
            c.rollback();
        }
        assertEquals(0, count("SELECT count(*) FROM baobab_native.native_placement WHERE ad_client_id = 41"));
    }
}
