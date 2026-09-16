package org.nabhold.baobab.erp.events;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.nabhold.baobab.erp.context.ContextResolver;
import org.nabhold.baobab.erp.mapping.CanonicalMappingResolver;
import org.nabhold.baobab.erp.outbox.OutboxPublisher;
import org.osgi.service.event.Event;

/**
 * Exercises BaobabCanonicalMappingEventHandler against a real org.osgi.service.event.Event
 * (not a mock) and small recording ContextResolver/CanonicalMappingResolver doubles --
 * this class's own job is proving the handler extracts AD_Client_ID/AD_Org_ID/tableName/
 * recordId correctly from a real event and derives the tenant per event (never a
 * process-wide assumption), not re-proving BaobabContextResolver's or
 * BaobabMappingResolver's HTTP wire format, which their own tests already cover against
 * real local HTTP servers. FakeNativePO stands in for org.compiere.model.PO, which isn't
 * available at compile time; it exposes only the three methods the handler calls
 * reflectively.
 */
class BaobabCanonicalMappingEventHandlerTest {

    private static final String TOPIC = "adempiere/po/postCreate";
    private static final String CANONICAL_ID = "e4a8ccd4-21cb-43b7-915f-1434d9aef07a";

    private static Event bPartnerEvent(Object po) {
        return nativeEvent("C_BPartner", po);
    }

    private static Event nativeEvent(String tableName, Object po) {
        Map<String, Object> properties = new HashMap<>();
        properties.put("tableName", tableName);
        properties.put("event.data", po);
        return new Event(TOPIC, properties);
    }

    @Test
    void resolvesOtherMappedTablesTheSameWay() {
        // EventsActivator filters topics to C_BPartner/M_Product/C_Order/C_Invoice
        // (ADR-ERP-007 §170's near-term slice); the handler itself reads "tableName"
        // generically and must not be coupled to any one of them.
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        handler.handleEvent(nativeEvent("M_Product", new FakeNativePO(555, 1000, 1)));

        assertEquals("M_Product", mappingResolver.table);
        assertEquals(555, mappingResolver.recordId);
        assertEquals(1, outboxPublisher.published.size());
        assertEquals("erp.product.synced.v1", outboxPublisher.published.get(0).eventType);
    }

    @Test
    void derivesTenantPerEventThenResolvesCanonicalId() {
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        handler.handleEvent(bPartnerEvent(new FakeNativePO(1001, 1000, 1)));

        assertEquals(1000, contextResolver.adClientId);
        assertEquals(1, contextResolver.adOrgId);
        assertEquals("nabhold", mappingResolver.tenantId);
        assertEquals("C_BPartner", mappingResolver.table);
        assertEquals(1001, mappingResolver.recordId);
    }

    @Test
    void secondClientOnTheSameJvmResolvesToItsOwnTenant() {
        // The classic multi-client-per-instance case (ADR-ERP-003's default topology):
        // two different AD_Client_IDs in the same process must resolve to two different
        // tenants, never the same one.
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("thamani", "thamani-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        handler.handleEvent(bPartnerEvent(new FakeNativePO(42, 2000, 3)));

        assertEquals(2000, contextResolver.adClientId);
        assertEquals(3, contextResolver.adOrgId);
        assertEquals("thamani", mappingResolver.tenantId);
    }

    @Test
    void unmappedClientSkipsMappingResolutionEntirely() {
        RecordingContextResolver contextResolver = RecordingContextResolver.notFound();
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        handler.handleEvent(bPartnerEvent(new FakeNativePO(1001, 9999, 9)));

        assertTrue(contextResolver.called);
        assertFalse(mappingResolver.called, "mapping resolver must not be called without a resolved tenant");
        assertTrue(outboxPublisher.published.isEmpty(), "nothing to publish without a resolved canonical id");
    }

    @Test
    void missingMappingDoesNotThrow() {
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.notFound();
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        handler.handleEvent(bPartnerEvent(new FakeNativePO(999999, 1000, 1)));

        assertTrue(mappingResolver.called, "mapping resolver should still have been called");
        assertTrue(outboxPublisher.published.isEmpty(), "nothing to publish without a resolved canonical id");
    }

    @Test
    void missingTableNamePropertySkipsResolutionEntirely() {
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);
        Event eventWithoutTableName = new Event(TOPIC, Map.of("event.data", new FakeNativePO(1001, 1000, 1)));

        handler.handleEvent(eventWithoutTableName);

        assertFalse(contextResolver.called, "context resolver must not be called without a tableName property");
        assertFalse(mappingResolver.called, "mapping resolver must not be called without a tableName property");
    }

    @Test
    void missingEventDataSkipsResolutionEntirely() {
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);
        Event eventWithoutData = new Event(TOPIC, Map.of("tableName", "C_BPartner"));

        handler.handleEvent(eventWithoutData);

        assertFalse(contextResolver.called, "resolvers must not be called without a PO to read ids from");
        assertFalse(mappingResolver.called, "resolvers must not be called without a PO to read ids from");
    }

    @Test
    void publishesTheResolvedFactWithCanonicalIdAndCorrelationId() {
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = new RecordingOutboxPublisher();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        handler.handleEvent(bPartnerEvent(new FakeNativePO(1001, 1000, 1)));

        assertEquals(1, outboxPublisher.published.size());
        RecordingOutboxPublisher.PublishedEvent published = outboxPublisher.published.get(0);
        assertEquals("erp.business-partner.synced.v1", published.eventType);
        assertEquals("nabhold", published.tenantId);
        assertEquals("nabhold-legal", published.legalEntityId);
        assertEquals("nabhold:C_BPartner:1001", published.correlationId);
        assertEquals("C_BPartner", published.payload.get("table"));
        assertEquals(1001, published.payload.get("native_record_id"));
        assertEquals(CANONICAL_ID, published.payload.get("canonical_id"));
    }

    @Test
    void outboxPublicationFailureIsSwallowedNotRethrown() {
        RecordingContextResolver contextResolver = RecordingContextResolver.returning("nabhold", "nabhold-legal");
        RecordingMappingResolver mappingResolver = RecordingMappingResolver.returning(CANONICAL_ID);
        RecordingOutboxPublisher outboxPublisher = RecordingOutboxPublisher.failing();
        BaobabCanonicalMappingEventHandler handler =
                new BaobabCanonicalMappingEventHandler(contextResolver, mappingResolver, outboxPublisher);

        // Must not throw: the iDempiere operation that triggered this event already
        // committed, so a publish failure here must never propagate.
        handler.handleEvent(bPartnerEvent(new FakeNativePO(1001, 1000, 1)));
    }

    /** Stands in for org.compiere.model.PO: only the reflectively-called methods matter. */
    static final class FakeNativePO {
        private final int id;
        private final int adClientId;
        private final int adOrgId;

        FakeNativePO(int id, int adClientId, int adOrgId) {
            this.id = id;
            this.adClientId = adClientId;
            this.adOrgId = adOrgId;
        }

        public int get_ID() {
            return id;
        }

        public int getAD_Client_ID() {
            return adClientId;
        }

        public int getAD_Org_ID() {
            return adOrgId;
        }
    }

    /** Records the AD_Client_ID/AD_Org_ID resolveTenant was called with; never touches the network. */
    static final class RecordingContextResolver implements ContextResolver {
        private final TenantIdentity identity;
        private final boolean notFound;
        boolean called;
        int adClientId;
        int adOrgId;

        private RecordingContextResolver(TenantIdentity identity, boolean notFound) {
            this.identity = identity;
            this.notFound = notFound;
        }

        static RecordingContextResolver returning(String tenantId, String legalEntityId) {
            return new RecordingContextResolver(new TenantIdentity(tenantId, legalEntityId), false);
        }

        static RecordingContextResolver notFound() {
            return new RecordingContextResolver(null, true);
        }

        @Override
        public ResolvedContext resolve(String tenantId, String legalEntityId) {
            throw new UnsupportedOperationException("not used by this handler");
        }

        @Override
        public TenantIdentity resolveTenant(int adClientId, int adOrgId) throws ContextResolutionException {
            this.called = true;
            this.adClientId = adClientId;
            this.adOrgId = adOrgId;
            if (notFound) {
                throw new ContextResolutionException("no mapping for " + adClientId + "/" + adOrgId);
            }
            return identity;
        }
    }

    /** Records the arguments resolveToCanonical was called with; never touches the network. */
    static final class RecordingMappingResolver implements CanonicalMappingResolver {
        private final String canonicalId;
        private final boolean notFound;
        boolean called;
        String tenantId;
        String table;
        int recordId;

        private RecordingMappingResolver(String canonicalId, boolean notFound) {
            this.canonicalId = canonicalId;
            this.notFound = notFound;
        }

        static RecordingMappingResolver returning(String canonicalId) {
            return new RecordingMappingResolver(canonicalId, false);
        }

        static RecordingMappingResolver notFound() {
            return new RecordingMappingResolver(null, true);
        }

        @Override
        public NativeRecordRef resolveToNative(String tenantId, String canonicalType, String canonicalId) {
            throw new UnsupportedOperationException("not used by this handler");
        }

        @Override
        public String resolveToCanonical(String tenantId, String nativeTable, int nativeId)
                throws MappingNotFoundException {
            this.called = true;
            this.tenantId = tenantId;
            this.table = nativeTable;
            this.recordId = nativeId;
            if (notFound) {
                throw new MappingNotFoundException("no mapping for " + nativeTable + "#" + nativeId);
            }
            return canonicalId;
        }
    }

    /** Records every publish() call; never touches the network. */
    static final class RecordingOutboxPublisher implements OutboxPublisher {
        record PublishedEvent(
                String eventType, String tenantId, String legalEntityId, String correlationId,
                Map<String, Object> payload) {
        }

        final List<PublishedEvent> published = new ArrayList<>();
        private final boolean failing;

        RecordingOutboxPublisher() {
            this(false);
        }

        private RecordingOutboxPublisher(boolean failing) {
            this.failing = failing;
        }

        static RecordingOutboxPublisher failing() {
            return new RecordingOutboxPublisher(true);
        }

        @Override
        public void publish(
                String eventType, String tenantId, String legalEntityId, String correlationId,
                Map<String, Object> payload) throws OutboxPublicationException {
            if (failing) {
                throw new OutboxPublicationException("simulated baobab-app failure");
            }
            published.add(new PublishedEvent(eventType, tenantId, legalEntityId, correlationId, payload));
        }
    }
}
