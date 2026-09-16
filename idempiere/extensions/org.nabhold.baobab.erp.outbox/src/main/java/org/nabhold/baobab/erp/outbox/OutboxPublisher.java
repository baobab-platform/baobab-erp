package org.nabhold.baobab.erp.outbox;

import java.util.Map;

/**
 * Publishes a canonical event fact to baobab-app's transactional outbox
 * (ADR-ERP-004 SS44-51, ADR-ERP-006), for something this bundle's own callers have
 * already resolved canonical identity for (org.nabhold.baobab.erp.events'
 * CanonicalMappingResolver).
 *
 * <p><b>This is fire-after-commit, best-effort -- not one atomic Postgres
 * transaction with the iDempiere document post that triggered it.</b> ADR-ERP-004
 * SS49 describes the outbox INSERT happening "in the same transaction" as the
 * operational change; that is achievable for
 * {@code modules/order_to_cash}'s own writes, where the operational change (a new
 * row in {@code baobab.entity_mapping}) and the outbox row both live in the same
 * {@code baobab} Postgres schema. It is NOT achievable here: this bundle runs
 * inside iDempiere's own JVM, reacting to iDempiere's own
 * {@code adempiere/po/postCreate}/{@code postUpdate} events, which
 * org.nabhold.baobab.erp.events' own Javadoc already documents as firing
 * asynchronously, after iDempiere's own transaction has already committed
 * (INV-ERP-EXT-011) -- iDempiere's database and baobab's {@code baobab} schema are
 * two separate databases, so no single Postgres transaction can span both. Only
 * baobab-app's own insert into {@code baobab.event_outbox} is atomic, in its own
 * database; the gap between "iDempiere committed" and "outbox row written" is real
 * and accepted, exactly as it already is for
 * BaobabCanonicalMappingEventHandler's own tenant/mapping resolution calls this
 * publisher is invoked alongside.
 */
public interface OutboxPublisher {

    /**
     * @param eventType    a canonical {@code erp.*} event type, e.g. "erp.sales-order.accepted.v1".
     * @param tenantId     the Baobab tenant this fact belongs to (never iDempiere's own AD_Client_ID).
     * @param legalEntityId the resolved legal entity (ContextResolver.TenantIdentity#legalEntityId()).
     * @param correlationId ties this event back to the request/process that produced it.
     * @param payload      canonical fact fields; MinimalJson.writeObject's supported value types only
     *                     (String, Number, Boolean, null, one level of nested Map).
     * @throws OutboxPublicationException if baobab-app could not durably record the event. Callers
     *         (BaobabCanonicalMappingEventHandler) log and continue rather than propagate -- a failed
     *         publish here must never fail the iDempiere operation that already committed.
     */
    void publish(
            String eventType, String tenantId, String legalEntityId, String correlationId, Map<String, Object> payload)
            throws OutboxPublicationException;

    class OutboxPublicationException extends Exception {
        public OutboxPublicationException(String message) {
            super(message);
        }
    }
}
