package org.nabhold.baobab.erp.outbox;

import java.util.Map;
import org.nabhold.baobab.erp.integration.BaobabAppClient;
import org.nabhold.baobab.erp.integration.BaobabAppClientException;
import org.nabhold.baobab.erp.integration.WorkloadTokenProviderFactory;

/**
 * Publishes canonical events by calling baobab-app's {@code POST /outbox/record}
 * endpoint, backed by {@code modules/outbox}'s already-real Postgres-backed
 * transactional outbox (ADR-ERP-006). This bundle has no direct database access of
 * its own -- baobab-app is the only thing that touches the {@code baobab} schema,
 * matching every other bundle's convention.
 */
final class BaobabOutboxPublisher implements OutboxPublisher {

    /** Same property/default convention as BaobabContextResolver/BaobabMappingResolver. */
    static final String BASE_URL_PROPERTY = "baobab.app.base.url";
    private static final String DEFAULT_BASE_URL = "http://baobab-app:8000";

    private final BaobabAppClient client;

    BaobabOutboxPublisher() {
        this(new BaobabAppClient(System.getProperty(BASE_URL_PROPERTY, DEFAULT_BASE_URL),
                WorkloadTokenProviderFactory.fromSystemProperties()));
    }

    BaobabOutboxPublisher(BaobabAppClient client) {
        this.client = client;
    }

    @Override
    public void publish(
            String eventType, String tenantId, String legalEntityId, String correlationId, Map<String, Object> payload)
            throws OutboxPublicationException {
        if (eventType == null || eventType.isBlank() || tenantId == null || tenantId.isBlank()) {
            throw new OutboxPublicationException("eventType and tenantId are both required");
        }
        Map<String, Object> body = Map.of(
                "event_type", eventType,
                "tenant_id", tenantId,
                "entity_id", legalEntityId == null ? "" : legalEntityId,
                "correlation_id", correlationId == null ? "" : correlationId,
                "payload", payload == null ? Map.of() : payload);
        try {
            client.post("/outbox/record", body);
        } catch (BaobabAppClientException e) {
            throw new OutboxPublicationException("Could not record event via baobab-app: " + e.getMessage());
        }
    }
}
