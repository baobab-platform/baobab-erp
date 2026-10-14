package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class NativeFinanceAttributionTest {
    static final NativePlacement PLACEMENT = new NativePlacement(
            "0b6d1f9a-3c2e-4a8b-9d7f-5e4c3b2a1908", 2, "tn_synthetic01", "ei_erpstaging01",
            "2c8e4f6a-1b3d-4e5f-8a7c-9d0e1f2a3b4c", "SYNTHETIC-LE-01", "UG", 11, 11);
    static final NativeFinanceAttribution.Decision DECISION = new NativeFinanceAttribution.Decision(
            "a3e9c7d1-5b2f-4e6a-8c1d-9f0b7e3a2c54", "6f1c2a9e-4b7d-4c1e-9a3f-2d5e8b7c1a40",
            "7d2b9e4f-6a1c-4f3e-b8d5-0c9a8e7f6d21", "1e8f7d6c-5b4a-4392-8170-6f5e4d3c2b1a",
            "synthetic:mandate-evidence/01", Instant.parse("2026-10-01T00:00:00Z"), Instant.now().plusSeconds(20));
    static final NativeFinanceReadiness.FinanceBaseline BASELINE =
            new NativeFinanceReadiness.FinanceBaseline("SYNTHETIC-LE-01", 3);

    static NativeOperation operation(String table, int id) {
        return new NativeOperation(NativeOperation.GL_JOURNAL, "GL_Journal", 100,
                new NativeRecord(table, 11, 11, id, "model:TYPE_BEFORE_NEW", "native-trx", c -> null));
    }

    @Test
    void appendRecordsLineageOnTheNativeTransactionAndNeverCommitsIt() throws Exception {
        FakeJdbc db = new FakeJdbc();
        NativeFinanceAttribution ledger = new NativeFinanceAttribution(trx -> {
            assertEquals("native-trx", trx);
            return db.connection();
        });
        ledger.append(operation("Fact_Acct", 0), PLACEMENT, DECISION, BASELINE);
        assertEquals(1, db.updates.size());
        var p = db.updates.get(0);
        assertEquals(24, p.size());
        assertEquals("SYNTHETIC-LE-01", p.get(4));
        assertEquals(DECISION.decisionId(), p.get(14));
        assertEquals("erp.gl-journal.post", p.get(15));
        assertEquals("GL_Journal", p.get(16));
        assertEquals(100, p.get(17));
        assertEquals(DECISION.supersedesMandateId(), p.get(18));
        assertEquals(PLACEMENT.placementId(), p.get(21));
        assertEquals(3, p.get(24));
        assertEquals(0, db.commits, "ledger must not independently commit/rollback/close native Trx");
    }

    @Test
    void autocommitUnboundOrMismatchedEvidenceFailBeforeMutation() {
        FakeJdbc auto = new FakeJdbc();
        auto.autoCommit = true;
        assertThrows(IllegalStateException.class, () -> new NativeFinanceAttribution(t -> auto.connection())
                .append(operation("GL_Journal", 100), PLACEMENT, DECISION, BASELINE));
        NativeFinanceAttribution ledger = new NativeFinanceAttribution(t -> new FakeJdbc().connection());
        var forged = new NativeFinanceAttribution.Decision(DECISION.decisionId(), DECISION.contextId(),
                "forged-mandate", null, "e", DECISION.mandateEffectiveFrom(), DECISION.usableUntil());
        assertThrows(IllegalArgumentException.class,
                () -> ledger.append(operation("GL_Journal", 100), PLACEMENT, forged, BASELINE));
        var otherEntity = new NativeFinanceReadiness.FinanceBaseline("OTHER-LE", 1);
        assertThrows(IllegalArgumentException.class,
                () -> ledger.append(operation("GL_Journal", 100), PLACEMENT, DECISION, otherEntity));
    }

    @Test
    void reuseIsOnlyForAnExistingSourceDocumentInTheSameTransaction() throws Exception {
        FakeJdbc db = new FakeJdbc();
        db.answer = (sql, params) -> List.<Object[]>of(new Object[]{Boolean.TRUE});
        NativeFinanceAttribution ledger = new NativeFinanceAttribution(t -> db.connection());
        assertTrue(ledger.hasCurrent(operation("Fact_Acct", 0)));
        NativeOperation creating = new NativeOperation(NativeOperation.GL_JOURNAL, "GL_Journal", 0,
                new NativeRecord("GL_Journal", 11, 11, 0, "model:TYPE_BEFORE_NEW", "native-trx", c -> null));
        assertFalse(ledger.hasCurrent(creating), "a document being created has no prior authority");
    }
}
