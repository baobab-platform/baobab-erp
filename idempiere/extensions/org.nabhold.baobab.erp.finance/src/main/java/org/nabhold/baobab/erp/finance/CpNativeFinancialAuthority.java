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
import java.util.concurrent.TimeUnit;

import org.nabhold.baobab.erp.integration.PinnedSharedSchemas;
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

    private Map<String,Object> current(String route, Map<String,String> input,
            String requestContract, String responseContract) throws Exception {
        PinnedSharedSchemas.require(requestContract, input);
        String token = iamToken.get();
        if (token == null || token.isBlank() || token.length() > 7000
                || token.chars().anyMatch(c -> c <= 32 || c > 126)) {
            throw new IllegalStateException("IAM workload token unavailable");
        }
        // CP legal and documentary routes require different independently
        // registered JWT scopes; the workload is not authorised by this code.
        String json = PinnedSharedSchemas.encode(input);
        HttpRequest request = HttpRequest.newBuilder(cpOrigin.resolve(route))
                .timeout(Duration.ofSeconds(3))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .header("Cache-Control", "no-store")
                .POST(HttpRequest.BodyPublishers.ofString(json)).build();
        // Bound bytes before materialisation AND the complete response deadline.
        // ofInputStream completes at headers and would leave a slow body read
        // outside that deadline. The subscriber completes only after the body.
        var exchange = http.sendAsync(request, info -> new BoundedJsonBodySubscriber());
        try {
            HttpResponse<byte[]> response = exchange.get(3, TimeUnit.SECONDS);
            if (response.statusCode() != 200) throw new IllegalStateException("CP decision denied");
            return PinnedSharedSchemas.parse(responseContract, response.body());
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw interrupted;
        } finally {
            if (!exchange.isDone()) exchange.cancel(true);
        }
    }

    private static boolean recent(Object stamp, Instant now, long maxAgeSeconds, long maxFutureSeconds) {
        if (!(stamp instanceof String s)) return false;
        try {
            Instant value = Instant.parse(s);
            return !value.isBefore(now.minusSeconds(maxAgeSeconds))
                    && !value.isAfter(now.plusSeconds(maxFutureSeconds));
        } catch (RuntimeException invalid) { return false; }
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

    private NativeFinancialContextSource.NativeLease issueCurrentCpContext(
            NativeFinancialContextSource.NativeLease nativeScope) throws Exception {
        // The native source supplies the independently resolved operating
        // Organisation and market, NOT a grant or a reusable Context ID.
        // CP mints the Context for the SAME IAM workload that redeems it.
        Map<String,Object> response = current("/v1/platform-context/resolve", Map.of(
                "tenant_id", nativeScope.tenantId(),
                "organisation_id", nativeScope.organisationId(),
                "country_code", nativeScope.market()), "context_request", "context_response");
        if (!nativeScope.tenantId().equals(response.get("tenant_id"))
                || !nativeScope.organisationId().equals(response.get("organisation_id"))
                || !nativeScope.market().equals(response.get("country_code"))
                || !recent(response.get("resolved_at"), Instant.now(), 5, 1)) {
            throw new IllegalStateException("CP could not mint exact runtime operating Context");
        }
        String context = boundString(response, "context_id");
        UUID.fromString(context);
        Instant expiry = Instant.parse(boundString(response, "expires_at"));
        if (!expiry.isAfter(Instant.now()) || expiry.isAfter(Instant.now().plusSeconds(600))) {
            throw new IllegalStateException("bounded active CP runtime context is required");
        }
        return new NativeFinancialContextSource.NativeLease(
                nativeScope.tenantId(), context, nativeScope.organisationId(),
                nativeScope.expectedLegalEntityId(), nativeScope.market(),
                nativeScope.role(), nativeScope.activity(), nativeScope.capability());
    }

    private record LegalProof(String mandateId, String evidenceReference) {}

    private LegalProof legalMandate(NativeFinancialContextSource.NativeLease lease, String operation) throws Exception {
        Map<String,Object> response = current("/internal/legal-actor/v1/assess", Map.of(
                "context_id", lease.contextId(), "role", lease.role(),
                "activity", lease.activity(), "market", lease.market(),
                "capability", lease.capability(), "operation_reference", operation), "legal_request", "legal_response");
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
        Instant evaluatedAt = Instant.parse(boundString(actor, "evaluated_at"));
        Instant until = Instant.parse(boundString(actor, "valid_until"));
        if (!until.isAfter(Instant.now()) || !until.isAfter(evaluatedAt)
                || until.isAfter(evaluatedAt.plusSeconds(31))) {
            throw new IllegalStateException("CP legal authority expired or too wide");
        }
        return new LegalProof(mandate, (String) evidences.get(0));
    }

    private void documentaryClear(NativeFinancialContextSource.NativeLease lease, String operation)
            throws Exception {
        Map<String,Object> r = current("/internal/documentary/v1/restrictions/assess", Map.of(
                "context_id", lease.contextId(), "market", lease.market(),
                "capability", lease.capability(), "operation_reference", operation), "documentary_request", "documentary_response");
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
        if (!until.isAfter(Instant.now()) || !until.isAfter(from)
                || until.isAfter(from.plusSeconds(2))) {
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
                    || lease.organisationId() == null
                    || lease.expectedLegalEntityId() == null || lease.market() == null
                    || lease.role() == null || lease.activity() == null || lease.capability() == null) {
                return false;
            }
            // Exact native tuple and transaction are embedded in CP's
            // operation_reference; a forged PO attribute cannot supply a lease.
            String operation = table + ":" + client + ":" + org + ":" + nativeId
                    + ":" + action + ":" + trx;
            if (operation.length() > 256) return false;
            lease = issueCurrentCpContext(lease);
            LegalProof proof = legalMandate(lease, operation);
            documentaryClear(lease, operation);
            if (!finance.currentCompanyFinanceReady(
                    table, client, org, nativeId, action, trx, lease.expectedLegalEntityId())) {
                return false;
            }
            // Refresh CP twice just before immutable same-transaction audit.
            LegalProof refreshed = legalMandate(lease, operation);
            if (!proof.equals(refreshed)) return false;
            documentaryClear(lease, operation);
            // Until this succeeds in native Trx, even an authorized actor
            // CANNOT enter the financial mutation path.
            attribution.append(table, client, org, nativeId, action, trx,
                    lease, proof.mandateId(), proof.evidenceReference());
            return true;
        } catch (Exception invalid) {
            // Never leak mandates, financial source data or IAM tokens in logs.
            return false;
        }
    }
}
