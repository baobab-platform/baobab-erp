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
        try (Connection c = transaction()) {
            payment = insertDoc(c, "c_payment", "isreceipt", "N");
            c.commit();
        }
        try (Connection c = transaction()) {
            var resolver = new NativeOperationResolver(trx -> c);
            // ERP-A (ADR-SHARED-037): an outbound payment that is neither online
            // nor from a payment selection is RECORDED under its own class only.
            assertEquals(NativeOperation.VENDOR_PAYMENT, resolver.classify(
                    record("C_Payment", payment, "gate-b-out", "IsReceipt", "N", "IsOnline", "N")).operationClass());
            assertNull(resolver.classify(record("C_Payment", payment, "gate-b-out", "IsReceipt", "N", "IsOnline", "Y")),
                    "an online outbound payment is a disbursement instruction");
            assertNull(resolver.classify(record("C_Payment", payment, "gate-b-out", "IsReceipt", "N")),
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
            vendorInvoice = insertPurchase(c, "c_invoice", ", c_doctypetarget_id, c_doctype_id", ", 202, 0");
            vendorPayment = insertDoc(c, "c_payment", "isreceipt", "N");
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
}
