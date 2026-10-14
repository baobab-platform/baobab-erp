package org.nabhold.baobab.erp.finance;

import java.lang.System.Logger;
import java.lang.System.Logger.Level;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceRegistration;
import org.nabhold.baobab.erp.integration.WorkloadTokenProvider;
import java.net.URI;
import org.osgi.util.tracker.ServiceTracker;

/**
 * Registers synchronous, process-local iDempiere 13 ModelValidator callbacks.
 * Reflection is used because the pinned iDempiere distribution does not
 * publish the native PO/ModelValidator classes as Maven build artifacts.
 *
 * iDempiere's ModelValidationEngine methods and timing constants are resolved
 * against the actual runtime types, not reimplemented as guessed integers.
 * A missing native engine or ModelValidator API causes OSGi activation failure.
 * Protected deployments MUST externally assert this bundle is ACTIVE and that
 * the callbacks are registered before exposing UI/REST/import/scheduler routes.
 */
public final class FinanceActivator implements BundleActivator {
    private static final Logger LOG = System.getLogger(FinanceActivator.class.getName());
    private static final Path HEALTH_MARKER = Path.of(
            "/opt/idempiere/.baobab/native-finance-veto-active");
    private ServiceTracker<NativeFinancialAuthority, NativeFinancialAuthority> authorities;
    private ServiceTracker<NativeFinancialContextSource, NativeFinancialContextSource> runtimeContexts;
    private ServiceTracker<NativeFinanceReadiness, NativeFinanceReadiness> financeReadiness;
    private ServiceRegistration<NativeFinancialAuthority> cpAdapterRegistration;
    private ServiceRegistration<NativeFinancialContextSource> placementRegistration;
    private ServiceRegistration<NativeFinanceReadiness> readinessRegistration;
    private final List<Registration> registrations = new ArrayList<>();
    private Object nativeEngine;
    private Class<?> validatorClass;
    private Object callback;

    private record Registration(String table, boolean document) {}

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
            Class<?> engineClass = Class.forName("org.compiere.model.ModelValidationEngine", true, loader);
            validatorClass = Class.forName("org.compiere.model.ModelValidator", true, loader);
            nativeEngine = engineClass.getMethod("get").invoke(null);
            if (nativeEngine == null) {
                throw new IllegalStateException("native ModelValidationEngine is unavailable");
            }
            InvocationHandler handler = (proxy, method, args) -> invoke(method, args);
            callback = Proxy.newProxyInstance(loader, new Class<?>[] {validatorClass}, handler);
            for (String table : NativeFinancePolicy.protectedTables()) {
                register(engineClass, table, false);
                if (isDocument(table)) {
                    register(engineClass, table, true);
                }
            }
            // A JAR and Equinox bundles.info entry are NOT enough for readiness.
            // Report ACTIVE only after every synchronous listener registration
            // succeeded. The image healthcheck verifies this JVM's PID.
            Files.writeString(HEALTH_MARKER, Long.toString(ProcessHandle.current().pid()));
            LOG.log(Level.INFO, "Baobab synchronous native finance veto registered for {0} tables",
                    NativeFinancePolicy.protectedTables().size());
        } catch (Exception | LinkageError unavailable) {
            stop(context);
            throw new IllegalStateException("BAOBAB_NATIVE_FINANCE_VETO_NOT_ACTIVE", unavailable);
        }
    }

    private void registerCpAuthority(BundleContext context) {
        String cp = System.getProperty("baobab.cp.native.base.url");
        String tokenUrl = System.getProperty("baobab.iam.token.url");
        String client = System.getProperty("baobab.iam.native.client.id", "baobab-erp-workload");
        String secret = System.getProperty("baobab.iam.native.client.secret");
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
                "context:resolve erp-posting-authority:resolve documentary:restriction-assess");
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

    private static boolean isDocument(String table) {
        return switch (table) {
            case "C_Order", "M_InOut", "C_Invoice", "C_Payment",
                    "C_AllocationHdr", "C_BankStatement", "C_Cash", "GL_Journal" -> true;
            default -> false;
        };
    }

    private void register(Class<?> engineClass, String table, boolean document)
            throws ReflectiveOperationException {
        Method method = engineClass.getMethod(
                document ? "addDocValidate" : "addModelChange", String.class, validatorClass);
        method.invoke(nativeEngine, table, callback);
        registrations.add(new Registration(table, document));
    }

    private Object invoke(Method method, Object[] args) {
        return switch (method.getName()) {
            case "getAD_Client_ID" -> 0; // registered globally for all iDempiere AD_Clients
            case "toString" -> "BaobabNativeFinanceModelValidator";
            case "hashCode" -> System.identityHashCode(callback);
            case "equals" -> callback == args[0];
            case "initialize", "login" -> null;
            case "modelChange", "docValidate" -> {
                Object po = args[0];
                int timing = (Integer) args[1];
                boolean document = method.getName().equals("docValidate");
                if (!isBeforeTiming(document, timing)) {
                    yield null;
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
                    yield verdict;
                } catch (ReflectiveOperationException | RuntimeException badRecord) {
                    yield "BAOBAB_NATIVE_FINANCE_DENIED: native record context unavailable";
                }
            }
            default -> null;
        };
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
        if (nativeEngine != null && validatorClass != null && callback != null) {
            for (Registration r : registrations) {
                try {
                    nativeEngine.getClass().getMethod(
                            r.document ? "removeDocValidate" : "removeModelChange",
                            String.class, validatorClass).invoke(nativeEngine, r.table, callback);
                } catch (ReflectiveOperationException unavailable) {
                    LOG.log(Level.WARNING, "Could not deregister native finance veto for " + r.table);
                }
            }
        }
        registrations.clear();
        nativeEngine = null;
        callback = null;
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
