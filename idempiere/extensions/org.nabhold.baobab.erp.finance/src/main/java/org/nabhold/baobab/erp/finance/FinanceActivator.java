package org.nabhold.baobab.erp.finance;

import java.lang.System.Logger;
import java.lang.System.Logger.Level;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Dictionary;
import java.util.Hashtable;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceRegistration;
import org.nabhold.baobab.erp.integration.WorkloadTokenProvider;
import org.nabhold.baobab.erp.integration.WorkloadTokenProviderFactory;
import java.net.URI;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventAdmin;
import org.osgi.service.event.EventConstants;
import org.osgi.service.event.EventHandler;
import org.osgi.util.tracker.ServiceTracker;

/**
 * Registers the synchronous native finance veto as an OSGi {@link EventHandler}
 * for iDempiere 13's BEFORE model-change and document topics on the protected
 * tables.
 *
 * <p>Why an event handler and not {@code ModelValidationEngine.addModelChange}:
 * the engine keys a listener added that way by {@code table + listener.getAD_Client_ID()}
 * unless it is in the engine's private global list (populated only from
 * {@code AD_ModelValidator} rows), and {@code fireModelChange}/{@code fireDocValidate}
 * look up only {@code table + "*"} and {@code table + po.getAD_Client_ID()}. A listener
 * reporting client 0 therefore fired for System records only: Gate D proved the
 * previous registration never ran for a real AD_Client. The same two methods then
 * send the OSGi event for the matching topic with {@code EventAdmin.sendEvent}
 * (synchronous, in the saving thread, for every client) and veto when any handler
 * adds to the event's {@code event.errorMessages} list. That is the supported
 * plugin hook (docs/architecture.md rule 2).
 *
 * <p>Topics are read from the installed {@code ModelValidator.tableEventTopics} /
 * {@code documentEventTopics} and correlated with its own TYPE_/TIMING_ constants,
 * never guessed. The handler is registered directly as an OSGi service, so
 * iDempiere's event-handler blacklist cannot disable it, and activation fails
 * unless an EventAdmin is present. A missing native API causes OSGi activation
 * failure. Protected deployments MUST externally assert this bundle is ACTIVE
 * before exposing UI/REST/import/scheduler routes.
 */
public final class FinanceActivator implements BundleActivator {
    private static final Logger LOG = System.getLogger(FinanceActivator.class.getName());
    private static final Path HEALTH_MARKER = Path.of(
            "/opt/idempiere/.baobab/native-finance-veto-active");
    // org.adempiere.base.event.IEventManager property names (iDempiere 13).
    static final String EVENT_DATA = "event.data";
    static final String EVENT_ERROR_MESSAGES = "event.errorMessages";
    static final String TABLE_NAME_PROPERTY = "tableName";
    private ServiceTracker<NativeFinancialAuthority, NativeFinancialAuthority> authorities;
    private ServiceTracker<NativeFinancialContextSource, NativeFinancialContextSource> runtimeContexts;
    private ServiceTracker<NativeFinanceReadiness, NativeFinanceReadiness> financeReadiness;
    private ServiceRegistration<NativeFinancialAuthority> cpAdapterRegistration;
    private ServiceRegistration<NativeFinancialContextSource> placementRegistration;
    private ServiceRegistration<NativeFinanceReadiness> readinessRegistration;
    private ServiceRegistration<?> vetoRegistration;
    private Class<?> validatorClass;

    /** A native topic and the timing it carries, from the installed API. */
    record NativeTopic(boolean document, int timing) {}

    @Override
    public void start(BundleContext context) throws Exception {
        authorities = new ServiceTracker<>(context, NativeFinancialAuthority.class, null);
        authorities.open();
        runtimeContexts = new ServiceTracker<>(context, NativeFinancialContextSource.class, null);
        runtimeContexts.open();
        financeReadiness = new ServiceTracker<>(context, NativeFinanceReadiness.class, null);
        financeReadiness.open();
        try {
            // P0-04B ERP: the platform-owned placement and Finance readiness
            // providers read only governed tables on the native transaction.
            // They confer no authority; CP still decides every operation.
            placementRegistration = context.registerService(NativeFinancialContextSource.class,
                    new PlacementContextSource(NativeConnections.IDEMPIERE), null);
            readinessRegistration = context.registerService(NativeFinanceReadiness.class,
                    new BaselineFinanceReadiness(NativeConnections.IDEMPIERE), null);
            registerCpAuthority(context);
            ClassLoader loader = FinanceActivator.class.getClassLoader();
            validatorClass = Class.forName("org.compiere.model.ModelValidator", true, loader);
            // sendEvent silently delivers nothing without an EventAdmin: refuse to report ACTIVE.
            if (context.getServiceReference(EventAdmin.class) == null) {
                throw new IllegalStateException("OSGi EventAdmin is unavailable");
            }
            Map<String, NativeTopic> topics = beforeTopics();
            if (topics.isEmpty()) {
                throw new IllegalStateException("no native BEFORE topics found");
            }
            Dictionary<String, Object> properties = new Hashtable<>();
            properties.put(EventConstants.EVENT_TOPIC, topics.keySet().toArray(String[]::new));
            properties.put(EventConstants.EVENT_FILTER, tableFilter());
            EventHandler veto = event -> handle(event, topics.get(event.getTopic()));
            vetoRegistration = context.registerService(EventHandler.class.getName(), veto, properties);
            // A JAR and Equinox bundles.info entry are NOT enough for readiness.
            // Report ACTIVE only after the synchronous handler is registered.
            // The image healthcheck verifies this JVM's PID.
            Files.writeString(HEALTH_MARKER, Long.toString(ProcessHandle.current().pid()));
            LOG.log(Level.INFO, "Baobab synchronous native finance veto registered for {0} tables on {1} topics",
                    NativeFinancePolicy.protectedTables().size(), topics.size());
        } catch (Exception | LinkageError unavailable) {
            stop(context);
            throw new IllegalStateException("BAOBAB_NATIVE_FINANCE_VETO_NOT_ACTIVE", unavailable);
        }
    }

    /** Every BEFORE (or unrecognised) model and document topic of the installed API. */
    Map<String, NativeTopic> beforeTopics() throws ReflectiveOperationException {
        Map<String, NativeTopic> topics = new LinkedHashMap<>();
        for (boolean document : new boolean[] {false, true}) {
            String[] names = (String[]) validatorClass
                    .getField(document ? "documentEventTopics" : "tableEventTopics").get(null);
            for (int timing = 0; timing < names.length; timing++) {
                if (names[timing] != null && !names[timing].isBlank() && isBeforeTiming(document, timing)) {
                    topics.put(names[timing], new NativeTopic(document, timing));
                }
            }
        }
        return topics;
    }

    static String tableFilter() {
        StringBuilder filter = new StringBuilder("(|");
        for (String table : NativeFinancePolicy.protectedTables()) {
            filter.append('(').append(TABLE_NAME_PROPERTY).append('=').append(table).append(')');
        }
        return filter.append(')').toString();
    }

    /** Synchronous delivery: a verdict added to the native error list vetoes the save or action. */
    @SuppressWarnings("unchecked")
    void handle(Event event, NativeTopic topic) {
        Object errors = event.getProperty(EVENT_ERROR_MESSAGES);
        String verdict;
        try {
            verdict = topic == null
                    ? "BAOBAB_NATIVE_FINANCE_DENIED: unrecognised native topic " + event.getTopic()
                    : evaluate(event.getProperty(EVENT_DATA), topic.document(), topic.timing());
        } catch (RuntimeException | LinkageError unexpected) {
            verdict = "BAOBAB_NATIVE_FINANCE_DENIED: native record context unavailable";
        }
        if (verdict == null) {
            return;
        }
        if (errors instanceof List<?> list) {
            ((List<Object>) list).add(verdict);
        } else {
            // Not an iDempiere-originated event: nothing to veto through.
            LOG.log(Level.ERROR, "native finance veto could not be delivered: " + verdict);
        }
    }

    private void registerCpAuthority(BundleContext context) {
        String cp = System.getProperty("baobab.cp.native.base.url");
        String tokenUrl = System.getProperty("baobab.iam.token.url");
        String client = System.getProperty("baobab.iam.native.client.id", "baobab-erp-workload");
        // Preferably a mounted file (baobab.iam.native.client.secret.file): never on the command line.
        String secret = WorkloadTokenProviderFactory.secret("baobab.iam.native.client.secret");
        // Absence is not a fallback: the native veto then has NO permit
        // provider and refuses every protected financial operation.
        if (cp == null || tokenUrl == null || secret == null || secret.isBlank()) {
            return;
        }
        URI authUrl = URI.create(tokenUrl);
        boolean loopbackTest = "test".equals(System.getProperty("baobab.erp.native.environment"))
                && ("127.0.0.1".equals(authUrl.getHost()) || "localhost".equals(authUrl.getHost()));
        if (!"https".equals(authUrl.getScheme()) && !(
                loopbackTest && "http".equals(authUrl.getScheme()))) {
            throw new IllegalArgumentException("native IAM workload token endpoint must be HTTPS");
        }
        WorkloadTokenProvider token = new WorkloadTokenProvider(
                tokenUrl, client, secret,
                "context:resolve erp-posting-authority:resolve documentary:restriction-assess",
                "baobab-control-plane");
        CpNativeFinancialAuthority service = new CpNativeFinancialAuthority(
                cp, () -> {
                    try {
                        return token.getAccessToken();
                    } catch (Exception unavailable) {
                        throw new IllegalStateException("IAM workload authentication unavailable");
                    }
                }, loopbackTest, new NativeOperationResolver(NativeConnections.IDEMPIERE),
                runtimeContexts, financeReadiness,
                new NativeFinanceAttribution(NativeConnections.IDEMPIERE));
        cpAdapterRegistration = context.registerService(NativeFinancialAuthority.class, service, null);
    }

    /** The policy verdict for one native PO at one native timing; null permits. */
    String evaluate(Object po, boolean document, int timing) {
        if (!isBeforeTiming(document, timing)) {
            return null;
        }
        if (po == null) {
            return "BAOBAB_NATIVE_FINANCE_DENIED: native record context unavailable";
        }
        try {
            String table = (String) po.getClass().getMethod("get_TableName").invoke(po);
            int client = (Integer) po.getClass().getMethod("getAD_Client_ID").invoke(po);
            int org = (Integer) po.getClass().getMethod("getAD_Org_ID").invoke(po);
            int nativeId = (Integer) po.getClass().getMethod("get_ID").invoke(po);
            String trxName = (String) po.getClass().getMethod("get_TrxName").invoke(po);
            Method getValue = po.getClass().getMethod("get_Value", String.class);
            // Column values come from the native PO being saved, never from a caller.
            NativeRecord record = new NativeRecord(table, client, org, nativeId,
                    document ? "document:" + constantName(timing, document) : "model:" + constantName(timing, document),
                    trxName, column -> {
                        try {
                            return getValue.invoke(po, column);
                        } catch (ReflectiveOperationException unreadable) {
                            return null;
                        }
                    });
            String verdict = NativeFinancePolicy.requireBeforeMutation(
                    record,
                    NativeFinancePolicy.protectedRuntime(
                        System.getProperty("baobab.erp.native.environment")),
                    authorities == null ? null : authorities.getService());
            if (verdict != null) {
                // Operator evidence: native identifiers only, never CP responses or credentials.
                LOG.log(Level.WARNING, "native finance veto: {0} {1} client={2} org={3} record={4} trx={5}: {6}",
                        table, record.action(), client, org, nativeId, trxName == null ? "none" : "present", verdict);
            }
            return verdict;
        } catch (ReflectiveOperationException | RuntimeException badRecord) {
            return "BAOBAB_NATIVE_FINANCE_DENIED: native record context unavailable";
        }
    }

    private String constantName(int value, boolean document) {
        // Model and document timings reuse integer values: never conflate them.
        String prefix = document ? "TIMING_BEFORE_" : "TYPE_BEFORE_";
        for (var field : validatorClass.getFields()) {
            if (field.getName().startsWith(prefix) && field.getType() == int.class) {
                try {
                    if (field.getInt(null) == value) {
                        return field.getName();
                    }
                } catch (IllegalAccessException ignored) {
                    // a missing public native constant cannot grant authority
                }
            }
        }
        return "UNKNOWN_" + value;
    }

    private boolean isBeforeTiming(boolean document, int timing) {
        String before = document ? "TIMING_BEFORE_" : "TYPE_BEFORE_";
        String after = document ? "TIMING_AFTER_" : "TYPE_AFTER_";
        for (var field : validatorClass.getFields()) {
            if (field.getType() != int.class
                    || !(field.getName().startsWith(before) || field.getName().startsWith(after))) {
                continue;
            }
            try {
                if (field.getInt(null) == timing) {
                    // Known AFTER notifications are irreversible observations,
                    // not an opportunity to veto an already accepted transaction.
                    return field.getName().startsWith(before);
                }
            } catch (IllegalAccessException ignored) {
                // unknown/unreadable native timing is denied below
            }
        }
        // An unrecognised before-compatible timing must not grant authority.
        return true;
    }

    @Override
    public void stop(BundleContext context) {
        try {
            Files.deleteIfExists(HEALTH_MARKER);
        } catch (java.io.IOException unavailable) {
            LOG.log(Level.WARNING, "Could not remove native finance activation marker");
        }
        if (vetoRegistration != null) {
            try {
                vetoRegistration.unregister();
            } catch (IllegalStateException alreadyGone) {
                // the framework already removed it
            }
            vetoRegistration = null;
        }
        if (authorities != null) {
            authorities.close();
            authorities = null;
        }
        if (cpAdapterRegistration != null) {
            cpAdapterRegistration.unregister();
            cpAdapterRegistration = null;
        }
        if (placementRegistration != null) {
            placementRegistration.unregister();
            placementRegistration = null;
        }
        if (readinessRegistration != null) {
            readinessRegistration.unregister();
            readinessRegistration = null;
        }
        if (runtimeContexts != null) {
            runtimeContexts.close();
            runtimeContexts = null;
        }
        if (financeReadiness != null) {
            financeReadiness.close();
            financeReadiness = null;
        }
    }
}
