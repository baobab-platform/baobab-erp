package org.nabhold.baobab.erp.finance;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Supplier;

import org.nabhold.baobab.erp.integration.MinimalJson;
import org.nabhold.baobab.erp.integration.WorkloadTokenProvider;
import org.osgi.util.tracker.ServiceTracker;

/**
 * Native server-side PEP for CP LA-05A and PEO-02T, over IAM workload tokens.
 * CP redeems context owner/issuer+sub, tenant status and revocation itself;
 * this adapter independently checks every response's exact operation,
 * actor, policy and non-grant semantics. Native finance readiness is separate.
 *
 * Network I/O is synchronous because ModelValidator is synchronous; bounded
 * timeouts are critical. Any lookup, IAM failure or malformed evidence denies.
 */
public final class CpNativeFinancialAuthority implements NativeFinancialAuthority {
    private final URI cpOrigin;
    private final Supplier<String> iamToken;
    private final HttpClient http;
    private final ServiceTracker<NativeFinancialContextSource, NativeFinancialContextSource> leaseSource;
    private final ServiceTracker<NativeFinanceReadiness, NativeFinanceReadiness> readiness;
    private final NativeFinanceAttribution attribution;

    public CpNativeFinancialAuthority(
            String cpUrl, Supplier<String> token, boolean allowTestLoopback,
            ServiceTracker<NativeFinancialContextSource, NativeFinancialContextSource> leaseSource,
            ServiceTracker<NativeFinanceReadiness, NativeFinanceReadiness> readiness,
            NativeFinanceAttribution attribution) {
        this.cpOrigin = URI.create(cpUrl);
        if (cpOrigin.getUserInfo() != null || cpOrigin.getQuery() != null || cpOrigin.getFragment() != null
                || !("/".equals(cpOrigin.getPath()) || cpOrigin.getPath().isEmpty())
                || cpOrigin.getHost() == null || !(
                  cpOrigin.getScheme().equals("https") || allowTestLoopback
                  && cpOrigin.getScheme().equals("http")
                  && ("localhost".equals(cpOrigin.getHost()) || "127.0.0.1".equals(cpOrigin.getHost())))) {
            throw new IllegalArgumentException("CP origin must be HTTPS (test-only loopback allowed)");
        }
        this.iamToken = Objects.requireNonNull(token);
        this.leaseSource = leaseSource;
        this.readiness = readiness;
        this.attribution = Objects.requireNonNull(attribution);
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    private Map<String,Object> current(String route, Map<String,String> input) throws Exception {
        String token = iamToken.get();
        if (token == null || token.isBlank() || token.length() > 7000
                || token.chars().anyMatch(c -> c <= 32 || c > 126)) {
            throw new IllegalStateException("IAM workload token unavailable");
        }
        // CP legal and documentary routes require different independently
        // registered JWT scopes; the workload is not authorised by this code.
        String json = writeFlat(input);
        HttpRequest request = HttpRequest.newBuilder(cpOrigin.resolve(route))
                .timeout(Duration.ofSeconds(3))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .header("Cache-Control", "no-store")
                .POST(HttpRequest.BodyPublishers.ofString(json)).build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200 || response.body().length() > 16384) {
            throw new IllegalStateException("CP decision unavailable or denied");
        }
        return MinimalJson.parseObject(response.body());
    }

    private static String writeFlat(Map<String,String> values) {
        // CP contract keys and values are JSON encoded; no header or path
        // injection, no dynamic route data.
        StringBuilder s = new StringBuilder("{");
        for (Map.Entry<String,String> entry : values.entrySet()) {
            if (s.length() > 1) s.append(',');
            s.append('"').append(escape(entry.getKey())).append("":"")
             .append(escape(entry.getValue())).append('"');
        }
        return s.append('}').toString();
    }

    private static String escape(String s) {
        return s.replace("\\","\\\\").replace("\"","\\\"")
                .replace("\n","\\n").replace("\r","\\r");
    }

    private static boolean recent(Object stamp, Instant now, long maxAgeSeconds, long maxFutureSeconds) {
        if (!(stamp instanceof String s)) return false;
        try {
            Instant value = Instant.parse(s);
            return !value.isBefore(now.minusSeconds(maxAgeSeconds))
                    && value.isAfter(now.minusSeconds(1))
                    || (!valueIsAfterFuture(value, now, maxFutureSeconds)
                        && !value.isBefore(now.minusSeconds(maxAgeSeconds)));
        } catch (RuntimeException invalid) { return false; }
    }

    private static boolean valueIsAfterFuture(Instant value, Instant now, long seconds) {
        return value.isAfter(now.plusSeconds(seconds));
    }

    @SuppressWarnings("unchecked")
    private static Map<String,Object> nested(Map<String,Object> outer, String key) {
        Object node = outer.get(key);
        if (!(node instanceof Map<?,?>)) throw new IllegalStateException("missing CP decision");
        return (Map<String,Object>) node;
    }

    private static String boundString(Map<String,Object> map, String name) {
        Object value = map.get(name);
        if (!(value instanceof String s) || s.isBlank() || s.length() > 256) {
            throw new IllegalStateException("missing CP decision field");
        }
        return s;
    }

    private String legalMandate(NativeFinancialContextSource.NativeLease lease, String operation) throws Exception {
        Map<String,Object> response = current("/internal/legal-actor/v1/assess", Map.of(
                "context_id", lease.contextId(), "role", lease.role(),
                "activity", lease.activity(), "market", lease.market(),
                "capability", lease.capability(), "operation_reference", operation));
        if (!lease.contextId().equals(response.get("context_id"))
                || !operation.equals(response.get("operation_reference"))
                || !Boolean.FALSE.equals(response.get("provider_permissions_granted"))) {
            throw new IllegalStateException("unbound CP legal actor response");
        }
        Map<String,Object> actor = nested(response, "legal_actor_resolution");
        if (!"AUTHORIZED".equals(actor.get("outcome"))
                || !lease.expectedLegalEntityId().equals(actor.get("responsible_legal_entity_id"))
                || !(actor.get("evidence_references") instanceof List<?> evidences)
                || evidences.isEmpty() || evidences.stream().anyMatch(x -> !(x instanceof String s) || s.isBlank())
                || !recent(actor.get("evaluated_at"), Instant.now(), 30, 1)) {
            throw new IllegalStateException("CP legal authority not current");
        }
        String mandate = boundString(actor, "mandate_id");
        UUID.fromString(mandate);
        Instant until = Instant.parse(boundString(actor, "valid_until"));
        if (!until.isAfter(Instant.now()) || until.isAfter(Instant.now().plusSeconds(32))) {
            throw new IllegalStateException("CP legal authority expired or too wide");
        }
        return mandate;
    }

    private void documentaryClear(NativeFinancialContextSource.NativeLease lease, String operation)
            throws Exception {
        Map<String,Object> r = current("/internal/documentary/v1/restrictions/assess", Map.of(
                "context_id", lease.contextId(), "market", lease.market(),
                "capability", lease.capability(), "operation_reference", operation));
        if (!lease.contextId().equals(r.get("context_id"))
                || !lease.organisationId().equals(r.get("organisation_id"))
                || !lease.market().equals(r.get("market"))
                || !lease.capability().equals(r.get("capability"))
                || !operation.equals(r.get("operation_reference"))
                || !Boolean.FALSE.equals(r.get("blocked"))
                || !Boolean.FALSE.equals(r.get("authority_granted"))
                || !"ADR-BCP-026/PEO-02T:negative-only".equals(r.get("policy_reference"))
                || !recent(r.get("evaluated_at"), Instant.now(), 3, 1)) {
            throw new IllegalStateException("CP documentary restriction denies");
        }
        Instant from = Instant.parse(boundString(r, "evaluated_at"));
        Instant until = Instant.parse(boundString(r, "expires_at"));
        if (!until.isAfter(Instant.now()) || until.isAfter(from.plusSeconds(2))) {
            throw new IllegalStateException("CP documentary decision expired");
        }
    }

    @Override
    public boolean currentlyAuthorised(
            String table, int client, int org, int nativeId, String action, String trx) {
        try {
            NativeFinancialContextSource contexts = leaseSource == null ? null : leaseSource.getService();
            NativeFinanceReadiness finance = readiness == null ? null : readiness.getService();
            if (contexts == null || finance == null || trx == null || trx.isBlank()
                    || client <= 0 || org <= 0 || nativeId < 0) return false;
            NativeFinancialContextSource.NativeLease lease =
                    contexts.currentLease(table, client, org, nativeId, action, trx);
            if (lease == null || lease.tenantId() == null || lease.tenantId().isBlank()
                    || lease.organisationId() == null || lease.contextId() == null
                    || lease.expectedLegalEntityId() == null || lease.market() == null
                    || lease.role() == null || lease.activity() == null || lease.capability() == null) {
                return false;
            }
            // Exact native tuple and transaction are embedded in CP's
            // operation_reference; a forged PO attribute cannot supply a lease.
            String operation = table + ":" + client + ":" + org + ":" + nativeId
                    + ":" + action + ":" + trx;
            if (operation.length() > 256) return false;
            String mandate = legalMandate(lease, operation);
            documentaryClear(lease, operation);
            if (!finance.currentCompanyFinanceReady(
                    table, client, org, nativeId, action, trx, lease.expectedLegalEntityId())) {
                return false;
            }
            // Refresh CP twice just before immutable same-transaction audit.
            String refreshed = legalMandate(lease, operation);
            if (!mandate.equals(refreshed)) return false;
            documentaryClear(lease, operation);
            // Until this succeeds in native Trx, even an authorized actor
            // CANNOT enter the financial mutation path.
            attribution.append(table, client, org, nativeId, action, trx,
                    lease, mandate, "cp/legal-actor/mandate/" + mandate);
            return true;
        } catch (Exception invalid) {
            // Never leak mandates, financial source data or IAM tokens in logs.
            return false;
        }
    }
}
