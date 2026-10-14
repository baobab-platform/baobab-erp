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
}
