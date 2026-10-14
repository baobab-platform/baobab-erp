package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.nabhold.baobab.erp.integration.PinnedSharedSchemas;

/**
 * Synthetic CP over loopback HTTP, synthetic placement and readiness. Proves
 * the ERP PEP's acceptance rules for ADR-SHARED-034 decisions only: it is not
 * evidence of CP standing, IAM admission, a real mandate or real posting.
 */
class CpNativePostingAuthorityTest {
    static final String ORG = "2c8e4f6a-1b3d-4e5f-8a7c-9d0e1f2a3b4c";
    static final String CONTEXT = "6f1c2a9e-4b7d-4c1e-9a3f-2d5e8b7c1a40";
    static final String MANDATE = "7d2b9e4f-6a1c-4f3e-b8d5-0c9a8e7f6d21";
    static final NativePlacement PLACEMENT = NativeFinanceAttributionTest.PLACEMENT;

    /** Mutable synthetic CP behaviour, one knob per denial path. */
    static final class Scenario {
        String outcome = "AUTHORIZED";
        String legalEntity = PLACEMENT.legalEntityId();
        String tenant = PLACEMENT.tenantId();
        String market = PLACEMENT.market();
        long leaseSeconds = 30;
        long evaluatedSecondsAgo = 0;
        boolean echoOperation = true;
        String refreshMandate = MANDATE;
        boolean documentaryBlocked = false;
        boolean grantsProvider = false;
    }

    private HttpServer server;
    private Scenario scenario;
    private final AtomicInteger postingCalls = new AtomicInteger();
    private final AtomicInteger calls = new AtomicInteger();

    @BeforeEach
    void start() throws IOException {
        scenario = new Scenario();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/platform-context/resolve", ex -> {
            calls.incrementAndGet();
            Instant now = Instant.now();
            respond(ex, Map.of("context_id", CONTEXT, "tenant_id", PLACEMENT.tenantId(),
                    "resolved_at", now.toString(), "expires_at", now.plusSeconds(60).toString(),
                    "country_code", PLACEMENT.market(), "market_id", "mkt_ug", "currency_code", "UGX",
                    "organisation_id", ORG, "organisation_type", "ORGANISATION"));
        });
        server.createContext("/internal/erp/v1/posting-authority/resolve", ex -> {
            calls.incrementAndGet();
            int n = postingCalls.incrementAndGet();
            Map<String, Object> req = PinnedSharedSchemas.parse("posting_request", ex.getRequestBody().readAllBytes());
            Instant evaluated = Instant.now().minusSeconds(scenario.evaluatedSecondsAgo);
            Map<String, Object> d = new HashMap<>();
            d.put("decision_id", java.util.UUID.randomUUID().toString());
            d.put("context_id", req.get("context_id"));
            d.put("engine_instance_id", req.get("engine_instance_id"));
            d.put("operation_class", req.get("operation_class"));
            d.put("native_placement_reference", req.get("native_placement_reference"));
            d.put("operation_reference", scenario.echoOperation ? req.get("operation_reference") : "erp/other/operation");
            d.put("outcome", scenario.outcome);
            d.put("tenant_id", scenario.tenant);
            d.put("operating_organisation_id", ORG);
            d.put("market", scenario.market);
            d.put("legal_actor_role", "ACCOUNTING_ENTITY");
            d.put("activity", "GENERAL_LEDGER_POSTING");
            d.put("evaluated_at", evaluated.toString());
            d.put("policy_reference", "ADR-SHARED-034/erp-posting-authority:v1");
            d.put("provider_permissions_granted", scenario.grantsProvider);
            if ("AUTHORIZED".equals(scenario.outcome)) {
                d.put("mandate_id", n == 1 ? MANDATE : scenario.refreshMandate);
                d.put("responsible_legal_entity_id", scenario.legalEntity);
                d.put("evidence_references", List.of("synthetic:mandate-evidence/01"));
                d.put("mandate_effective_from", "2026-10-01T00:00:00Z");
                d.put("expires_at", evaluated.plusSeconds(scenario.leaseSeconds).toString());
            }
            respond(ex, d);
        });
        server.createContext("/internal/documentary/v1/restrictions/assess", ex -> {
            calls.incrementAndGet();
            Map<String, Object> req = PinnedSharedSchemas.parse("documentary_request", ex.getRequestBody().readAllBytes());
            Instant now = Instant.now();
            respond(ex, Map.of("context_id", req.get("context_id"), "market", req.get("market"),
                    "capability", req.get("capability"), "operation_reference", req.get("operation_reference"),
                    "organisation_id", ORG, "blocked", scenario.documentaryBlocked, "authority_granted", false,
                    "policy_reference", "ADR-BCP-026/PEO-02T:negative-only",
                    "evaluated_at", now.toString(), "expires_at", now.plusSeconds(1).toString()));
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private static void respond(HttpExchange ex, Map<String, Object> body) throws IOException {
        byte[] bytes = PinnedSharedSchemas.encode(body).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(200, bytes.length);
        try (var out = ex.getResponseBody()) {
            out.write(bytes);
        }
    }

    private record Harness(CpNativeFinancialAuthority authority, FakeJdbc db) {}

    private Harness harness(NativePlacement placement, NativeFinanceReadiness.FinanceBaseline baseline) {
        FakeJdbc db = new FakeJdbc();
        db.answer = (sql, params) -> sql.contains("has_current_attribution")
                ? List.<Object[]>of(new Object[]{Boolean.FALSE}) : List.of();
        NativeConnections connections = trx -> db.connection();
        var authority = new CpNativeFinancialAuthority("http://127.0.0.1:" + server.getAddress().getPort(),
                () -> "synthetic-token", true, new NativeOperationResolver(connections),
                () -> operation -> placement, () -> (operation, p) -> baseline,
                new NativeFinanceAttribution(connections));
        return new Harness(authority, db);
    }

    private Harness harness() {
        return harness(PLACEMENT, NativeFinanceAttributionTest.BASELINE);
    }

    private static NativeRecord newJournal() {
        return new NativeRecord("GL_Journal", 11, 11, 0, "model:TYPE_BEFORE_NEW", "native-trx", c -> null);
    }

    @Test
    void currentExactAuthorityIsAttributedOnceWithItsLineage() {
        Harness h = harness();
        assertTrue(h.authority().currentlyAuthorised(newJournal()));
        assertEquals(2, postingCalls.get(), "decision is re-resolved before attribution");
        assertEquals(1, h.db().updates.size());
        var row = h.db().updates.get(0);
        assertEquals(MANDATE, row.get(5));
        assertEquals("erp.gl-journal.post", row.get(15));
        var until = ((java.sql.Timestamp) row.get(20)).toInstant();
        assertFalse(until.isAfter(Instant.now().plusSeconds(30)), "usable lease never exceeds 30 s");
    }

    @Test
    void everyNonExactDecisionDenies() {
        record Case(String name, java.util.function.Consumer<Scenario> mutate) {}
        for (Case c : List.of(
                new Case("not authorized", s -> s.outcome = "NO_APPLICABLE_MANDATE"),
                new Case("ambiguous", s -> s.outcome = "AMBIGUOUS"),
                new Case("other legal entity (group placement is not authority)", s -> s.legalEntity = "OTHER-LE"),
                new Case("other tenant", s -> s.tenant = "tn_other01"),
                new Case("wrong market", s -> s.market = "KE"),
                new Case("lease wider than 30 s", s -> s.leaseSeconds = 45),
                new Case("stale decision", s -> { s.evaluatedSecondsAgo = 40; s.leaseSeconds = 30; }),
                new Case("operation not echoed", s -> s.echoOperation = false),
                new Case("mandate changed on refresh", s -> s.refreshMandate = "1e8f7d6c-5b4a-4392-8170-6f5e4d3c2b1a"),
                new Case("documentary hold", s -> s.documentaryBlocked = true),
                new Case("claims provider permission", s -> s.grantsProvider = true))) {
            scenario = new Scenario();
            postingCalls.set(0);
            c.mutate().accept(scenario);
            Harness h = harness();
            assertFalse(h.authority().currentlyAuthorised(newJournal()), c.name());
            assertTrue(h.db().updates.isEmpty(), c.name() + " must not attribute");
        }
    }

    @Test
    void missingPlacementOrReadinessDeniesBeforeAnyAttribution() {
        Harness noPlacement = harness(null, NativeFinanceAttributionTest.BASELINE);
        assertFalse(noPlacement.authority().currentlyAuthorised(newJournal()));
        assertEquals(0, calls.get(), "no placement means no CP call at all");
        Harness notReady = harness(PLACEMENT, null);
        assertFalse(notReady.authority().currentlyAuthorised(newJournal()));
        assertTrue(notReady.db().updates.isEmpty());
        Harness otherEntityBaseline = harness(PLACEMENT, new NativeFinanceReadiness.FinanceBaseline("OTHER-LE", 1));
        assertFalse(otherEntityBaseline.authority().currentlyAuthorised(newJournal()));
    }

    @Test
    void purchaseSideAndConfigurationWritesHaveNoClassAndNeverReachCp() {
        Harness h = harness();
        NativeRecord vendorInvoice = new NativeRecord("C_Invoice", 11, 11, 0, "model:TYPE_BEFORE_NEW", "native-trx",
                c -> "IsSOTrx".equals(c) ? Boolean.FALSE : null);
        NativeRecord chart = new NativeRecord("C_ElementValue", 11, 11, 5, "model:TYPE_BEFORE_CHANGE", "native-trx", c -> null);
        assertFalse(h.authority().currentlyAuthorised(vendorInvoice));
        assertFalse(h.authority().currentlyAuthorised(chart));
        assertEquals(0, calls.get());
    }

    @Test
    void sameTransactionCurrentAttributionCoversFurtherWritesWithoutCp() {
        FakeJdbc db = new FakeJdbc();
        db.answer = (sql, params) -> List.<Object[]>of(new Object[]{Boolean.TRUE});
        NativeConnections connections = trx -> db.connection();
        var authority = new CpNativeFinancialAuthority("http://127.0.0.1:" + server.getAddress().getPort(),
                () -> "synthetic-token", true, new NativeOperationResolver(connections),
                () -> operation -> PLACEMENT, () -> (operation, p) -> NativeFinanceAttributionTest.BASELINE,
                new NativeFinanceAttribution(connections));
        NativeRecord line = new NativeRecord("GL_JournalLine", 11, 11, 0, "model:TYPE_BEFORE_NEW", "native-trx",
                c -> "GL_Journal_ID".equals(c) ? 100 : null);
        assertTrue(authority.currentlyAuthorised(line));
        assertEquals(0, calls.get(), "bounded same-transaction reuse makes no CP call");
        assertTrue(db.updates.isEmpty());
    }

    @Test
    void placementOfAnotherClientIsRejected() {
        NativePlacement foreign = new NativePlacement(PLACEMENT.placementId(), PLACEMENT.version(),
                PLACEMENT.tenantId(), PLACEMENT.engineInstanceId(), PLACEMENT.operatingOrganisationId(),
                PLACEMENT.legalEntityId(), PLACEMENT.market(), 99, 11);
        assertFalse(harness(foreign, NativeFinanceAttributionTest.BASELINE).authority().currentlyAuthorised(newJournal()));
        assertEquals(0, calls.get());
    }
}
