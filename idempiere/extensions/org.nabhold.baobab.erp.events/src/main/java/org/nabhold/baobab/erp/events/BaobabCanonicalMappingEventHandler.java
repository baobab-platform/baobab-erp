package org.nabhold.baobab.erp.events;

import java.lang.System.Logger;
import java.lang.System.Logger.Level;
import java.lang.reflect.Method;
import java.util.Map;
import org.nabhold.baobab.erp.context.ContextResolver;
import org.nabhold.baobab.erp.context.ContextResolver.ContextResolutionException;
import org.nabhold.baobab.erp.context.ContextResolver.TenantIdentity;
import org.nabhold.baobab.erp.mapping.CanonicalMappingResolver;
import org.nabhold.baobab.erp.mapping.CanonicalMappingResolver.MappingNotFoundException;
import org.nabhold.baobab.erp.outbox.OutboxPublisher;
import org.nabhold.baobab.erp.outbox.OutboxPublisher.OutboxPublicationException;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventHandler;
import org.osgi.util.tracker.ServiceTracker;

/**
 * Reacts to a real, iDempiere-fired PO_POST_CREATE/PO_POST_UPADTE event on C_BPartner by
 * deriving the owning tenant from the changed record's own AD_Client_ID/AD_Org_ID
 * (ContextResolver.resolveTenant, ADR-ERP-002) and then resolving its canonical Party
 * identity (CanonicalMappingResolver.resolveToCanonical, ADR-ERP-007). The tenant is
 * derived per event, never assumed for the whole process, because ADR-ERP-003's default
 * topology (ERP_SHARED_INSTANCE_DEDICATED_CLIENT) has one iDempiere runtime hosting
 * several AD_Clients (tenants) at once. Both resolutions are real HTTP calls to
 * baobab-app; PO_POST_CREATE/PO_POST_UPADTE fire asynchronously, after the triggering
 * transaction has committed (see org.compiere.model.PO#processAfterSave), so neither
 * runs inside a document transaction (ADR-ERP-004, INV-ERP-EXT-011).
 *
 * <p>Once canonical identity resolves, this publishes a generic {@code erp.*.synced.v1}
 * event (via OutboxPublisher) -- deliberately NOT one of the specific business-lifecycle
 * facts (e.g. "erp.sales-order.accepted.v1") modules/order_to_cash's own primary
 * integration path emits: this handler reacts to ANY native postCreate/postUpdate on
 * these tables, including ones made directly through iDempiere's own UI/API rather than
 * through our own order-to-cash commands, so it genuinely does not know whether a given
 * change means "just accepted", "still drafted", or "an unrelated field edited" -- only
 * that the record exists and is (now) canonically mapped. Its purpose is a reconciliation
 * safety net for native-side mutations that bypass our own API, not a duplicate of the
 * specific lifecycle events order_to_cash.service already emits on the primary path. A
 * publish failure is logged and swallowed, never rethrown: this handler must never fail
 * the iDempiere operation that already committed (matching this class's own fail-open
 * posture for a missing tenant/mapping resolution below).
 *
 * <p>This bundle has no compile-time dependency on any iDempiere class: the event's
 * "tableName" property is a plain String set by iDempiere's own EventManager, and the
 * only iDempiere-shaped values this class touches -- the PO's record id, AD_Client_ID
 * and AD_Org_ID -- are read via reflective calls to its public {@code get_ID()},
 * {@code getAD_Client_ID()} and {@code getAD_Org_ID()} methods, since
 * org.compiere.model.PO is not available at compile time (see idempiere/README.md for
 * why: no iDempiere Maven artifacts exist, and building against iDempiere's own
 * Tycho/p2 target platform is the exact blocker that has deferred the REST API plugin
 * work, per ADR-ERP-005).
 */
final class BaobabCanonicalMappingEventHandler implements EventHandler {

    private static final String TABLE_NAME_PROPERTY = "tableName";
    private static final String EVENT_DATA_PROPERTY = "event.data";

    private static final Logger LOG = System.getLogger(BaobabCanonicalMappingEventHandler.class.getName());

    /** iDempiere native table -> the generic "this record is now mapped" event type this
     * handler publishes for it. Deliberately narrower than ADR-ERP-016 SS221's full event
     * list -- see this class's own Javadoc for why. */
    private static final Map<String, String> SYNCED_EVENT_TYPE_BY_TABLE = Map.of(
            "C_BPartner", "erp.business-partner.synced.v1",
            "M_Product", "erp.product.synced.v1",
            "C_Order", "erp.sales-order.synced.v1",
            "C_Invoice", "erp.customer-invoice.synced.v1");

    private final ServiceTracker<ContextResolver, ContextResolver> contextTracker;
    private final ServiceTracker<CanonicalMappingResolver, CanonicalMappingResolver> mappingTracker;
    private final ServiceTracker<OutboxPublisher, OutboxPublisher> outboxTracker;
    private final ContextResolver contextResolver;
    private final CanonicalMappingResolver mappingResolver;
    private final OutboxPublisher outboxPublisher;

    /** Production constructor: all three services are looked up lazily from their trackers
     * on every event, since any of their bundles may come and go independently. */
    BaobabCanonicalMappingEventHandler(
            ServiceTracker<ContextResolver, ContextResolver> contextTracker,
            ServiceTracker<CanonicalMappingResolver, CanonicalMappingResolver> mappingTracker,
            ServiceTracker<OutboxPublisher, OutboxPublisher> outboxTracker) {
        this.contextTracker = contextTracker;
        this.mappingTracker = mappingTracker;
        this.outboxTracker = outboxTracker;
        this.contextResolver = null;
        this.mappingResolver = null;
        this.outboxPublisher = null;
    }

    /** Test constructor: bypasses OSGi service tracking entirely. */
    BaobabCanonicalMappingEventHandler(
            ContextResolver contextResolver, CanonicalMappingResolver mappingResolver, OutboxPublisher outboxPublisher) {
        this.contextTracker = null;
        this.mappingTracker = null;
        this.outboxTracker = null;
        this.contextResolver = contextResolver;
        this.mappingResolver = mappingResolver;
        this.outboxPublisher = outboxPublisher;
    }

    @Override
    public void handleEvent(Event event) {
        Object tableNameProperty = event.getProperty(TABLE_NAME_PROPERTY);
        if (!(tableNameProperty instanceof String tableName) || tableName.isBlank()) {
            LOG.log(Level.WARNING, "Event {0} has no tableName property; ignoring", event.getTopic());
            return;
        }

        Object po = event.getProperty(EVENT_DATA_PROPERTY);
        int recordId;
        int adClientId;
        int adOrgId;
        try {
            recordId = invokeIntGetter(po, "get_ID");
            adClientId = invokeIntGetter(po, "getAD_Client_ID");
            adOrgId = invokeIntGetter(po, "getAD_Org_ID");
        } catch (ReflectiveOperationException e) {
            LOG.log(Level.WARNING, "Could not read record/client/org id from event " + event.getTopic(), e);
            return;
        }

        ContextResolver activeContextResolver = contextTracker != null ? contextTracker.getService() : contextResolver;
        if (activeContextResolver == null) {
            LOG.log(Level.WARNING, "ContextResolver service is not available; ignoring {0} for {1}#{2}",
                    event.getTopic(), tableName, recordId);
            return;
        }

        TenantIdentity tenant;
        try {
            tenant = activeContextResolver.resolveTenant(adClientId, adOrgId);
        } catch (ContextResolutionException e) {
            LOG.log(Level.INFO, "No tenant mapping yet for AD_Client_ID={0} AD_Org_ID={1}: {2}",
                    adClientId, adOrgId, e.getMessage());
            return;
        }

        CanonicalMappingResolver activeMappingResolver = mappingTracker != null ? mappingTracker.getService() : mappingResolver;
        if (activeMappingResolver == null) {
            LOG.log(Level.WARNING, "CanonicalMappingResolver service is not available; ignoring {0} for {1}#{2}",
                    event.getTopic(), tableName, recordId);
            return;
        }

        String canonicalId;
        try {
            canonicalId = activeMappingResolver.resolveToCanonical(tenant.tenantId(), tableName, recordId);
            LOG.log(Level.INFO, "Resolved {0}#{1} to canonical id {2} for tenant {3}",
                    tableName, recordId, canonicalId, tenant.tenantId());
        } catch (MappingNotFoundException e) {
            LOG.log(Level.INFO, "No canonical mapping yet for {0}#{1} (tenant {2}): {3}",
                    tableName, recordId, tenant.tenantId(), e.getMessage());
            return;
        }

        String eventType = SYNCED_EVENT_TYPE_BY_TABLE.get(tableName);
        if (eventType == null) {
            // Filtered at subscription time (EventsActivator's FILTER_MAPPED_TABLES), so this
            // is defensive, not an expected path: nothing to publish for a table this handler
            // was never told how to name an event for.
            return;
        }

        OutboxPublisher activeOutboxPublisher = outboxTracker != null ? outboxTracker.getService() : outboxPublisher;
        if (activeOutboxPublisher == null) {
            LOG.log(Level.WARNING, "OutboxPublisher service is not available; not publishing {0} for {1}#{2}",
                    eventType, tableName, recordId);
            return;
        }

        String correlationId = tenant.tenantId() + ":" + tableName + ":" + recordId;
        try {
            activeOutboxPublisher.publish(
                    eventType, tenant.tenantId(), tenant.legalEntityId(), correlationId,
                    Map.of("table", tableName, "native_record_id", recordId, "canonical_id", canonicalId));
        } catch (OutboxPublicationException e) {
            // Never rethrown: the iDempiere operation that triggered this event already
            // committed, so a failure here must not fail it -- see this class's own Javadoc.
            LOG.log(Level.WARNING, "Could not publish " + eventType + " for " + tableName + "#" + recordId, e);
        }
    }

    /** Calls a no-arg int-returning method that every org.compiere.model.PO subclass
     * exposes, without requiring that class at compile time. */
    private static int invokeIntGetter(Object po, String methodName) throws ReflectiveOperationException {
        if (po == null) {
            throw new NoSuchMethodException("event has no \"" + EVENT_DATA_PROPERTY + "\" property");
        }
        Method getter = po.getClass().getMethod(methodName);
        return (Integer) getter.invoke(po);
    }
}
