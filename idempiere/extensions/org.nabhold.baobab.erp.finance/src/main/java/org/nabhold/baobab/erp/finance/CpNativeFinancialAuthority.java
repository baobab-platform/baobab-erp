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
 * Native server-side PEP for ADR-SHARED-034 ERP posting authority and PEO-02T,
 * over IAM workload tokens (P0-04B ERP, ADR-ERP-022).
 *
 * For each protected native write: classify it into one catalogued operation
 * and its source document; find the ERP-owned placement that applies; mint a
 * CP RUNTIME context for that placement's tenant, Organisation and market;
 * obtain CP's per-operation posting-authority decision; check the negative-only
 * documentary veto and ERP's own Finance readiness; re-resolve CP; then append
 * the attribution to the SAME native transaction. The database re-checks the
 * authority lease at COMMIT. CP decides legal authority; ERP alone decides
 * placement and Finance readiness. Neither substitutes for the other.
 *
 * Network I/O is synchronous because ModelValidator is synchronous; bounded
 * timeouts are critical. Any lookup, IAM failure or malformed evidence denies.
 */
public final class CpNativeFinancialAuthority implements NativeFinancialAuthority {
    /** ADR-SHARED-034: the longest any CP posting decision may be relied on. */
    static final long MAX_LEASE_SECONDS = 30;

    private final URI cpOrigin;
    private final Supplier<String> iamToken;
    private final HttpClient http;
    private final NativeOperationResolver operations;
    private final Supplier<NativeFinancialContextSource> placementSource;
    private final Supplier<NativeFinanceReadiness> readiness;
    private final NativeFinanceAttribution attribution;
    private final NativeDerivedWrites derived;

    public CpNativeFinancialAuthority(
            String cpUrl, Supplier<String> token, boolean allowTestLoopback,
            NativeOperationResolver operations,
            ServiceTracker<NativeFinancialContextSource, NativeFinancialContextSource> placementSource,
            ServiceTracker<NativeFinanceReadiness, NativeFinanceReadiness> readiness,
            NativeFinanceAttribution attribution) {
        this(cpUrl, token, allowTestLoopback, operations,
                placementSource == null ? () -> null : placementSource::getService,
                readiness == null ? () -> null : readiness::getService, attribution);
    }

    /** Same authority with the trusted providers supplied directly (OSGi-free tests). */
    CpNativeFinancialAuthority(
            String cpUrl, Supplier<String> token, boolean allowTestLoopback,
            NativeOperationResolver operations,
            Supplier<NativeFinancialContextSource> placementSource,
            Supplier<NativeFinanceReadiness> readiness,
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
        this.operations = operations;
        this.placementSource = Objects.requireNonNull(placementSource);
        this.readiness = Objects.requireNonNull(readiness);
        this.attribution = Objects.requireNonNull(attribution);
        this.derived = attribution.derivedWrites();
        this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    private Map<String,Object> current(String route, Map<String,?> input,
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

    /** CP mints a RUNTIME Context for the SAME IAM workload, for the placement's scope. */
    private String issueCurrentCpContext(NativePlacement placement) throws Exception {
        Map<String,Object> response = current("/v1/platform-context/resolve", Map.of(
                "tenant_id", placement.tenantId(),
                "organisation_id", placement.operatingOrganisationId(),
                "country_code", placement.market()), "context_request", "context_response");
        if (!placement.tenantId().equals(response.get("tenant_id"))
                || !placement.operatingOrganisationId().equals(response.get("organisation_id"))
                || !placement.market().equals(response.get("country_code"))
                || !recent(response.get("resolved_at"), Instant.now(), 5, 1)) {
            throw new IllegalStateException("CP could not mint exact runtime operating Context");
        }
        String context = boundString(response, "context_id");
        UUID.fromString(context);
        Instant expiry = Instant.parse(boundString(response, "expires_at"));
        if (!expiry.isAfter(Instant.now()) || expiry.isAfter(Instant.now().plusSeconds(600))) {
            throw new IllegalStateException("bounded active CP runtime context is required");
        }
        return context;
    }

    /**
     * CP's per-operation decision, accepted only when it is AUTHORIZED, echoes
     * this exact request, names the placement's tenant, Organisation, market and
     * legal entity, and respects the 30-second lease (ADR-SHARED-034 semantic
     * rules; role and activity are bound to the class by the pinned schema).
     */
    private NativeFinanceAttribution.Decision postingAuthority(
            String context, NativePlacement placement, NativeOperation operation, String reference) throws Exception {
        Map<String,Object> placementRef = Map.of(
                "placement_id", placement.placementId(), "placement_version", placement.version());
        Map<String,Object> request = Map.of(
                "context_id", context, "engine_instance_id", placement.engineInstanceId(),
                "operation_class", operation.operationClass(),
                "native_placement_reference", placementRef, "operation_reference", reference);
        Map<String,Object> d = current("/internal/erp/v1/posting-authority/resolve", request,
                "posting_request", "posting_decision");
        Instant received = Instant.now();
        Object echoedPlacement = d.get("native_placement_reference");
        if (!"AUTHORIZED".equals(d.get("outcome"))
                || !Boolean.FALSE.equals(d.get("provider_permissions_granted"))
                || !context.equals(d.get("context_id"))
                || !placement.engineInstanceId().equals(d.get("engine_instance_id"))
                || !operation.operationClass().equals(d.get("operation_class"))
                || !reference.equals(d.get("operation_reference"))
                || !(echoedPlacement instanceof Map<?,?> echoed)
                || !placement.placementId().equals(echoed.get("placement_id"))
                || !(echoed.get("placement_version") instanceof Number v) || v.intValue() != placement.version()
                || !placement.tenantId().equals(d.get("tenant_id"))
                || !placement.operatingOrganisationId().equals(d.get("operating_organisation_id"))
                || !placement.market().equals(d.get("market"))
                // A placement never creates authority: CP must name ITS legal entity.
                || !placement.legalEntityId().equals(d.get("responsible_legal_entity_id"))
                || !(d.get("evidence_references") instanceof List<?> evidences) || evidences.isEmpty()
                || !(evidences.get(0) instanceof String evidence) || evidence.isBlank()) {
            throw new IllegalStateException("CP posting authority not granted for this exact operation");
        }
        Instant evaluated = Instant.parse(boundString(d, "evaluated_at"));
        Instant expires = Instant.parse(boundString(d, "expires_at"));
        if (!recent(d.get("evaluated_at"), received, MAX_LEASE_SECONDS, 1)
                || !expires.isAfter(evaluated) || expires.isAfter(evaluated.plusSeconds(MAX_LEASE_SECONDS))
                || !expires.isAfter(received)) {
            throw new IllegalStateException("CP posting authority expired or too wide");
        }
        Instant usableUntil = expires.isBefore(received.plusSeconds(MAX_LEASE_SECONDS))
                ? expires : received.plusSeconds(MAX_LEASE_SECONDS);
        String decisionId = boundString(d, "decision_id");
        String mandate = boundString(d, "mandate_id");
        UUID.fromString(decisionId);
        UUID.fromString(mandate);
        Object supersedes = d.get("supersedes_mandate_id");
        return new NativeFinanceAttribution.Decision(decisionId, context, mandate,
                supersedes instanceof String s ? s : null, evidence,
                Instant.parse(boundString(d, "mandate_effective_from")), usableUntil);
    }

    /** PEO-02T negative-only veto, keyed by the operation class until finance keys exist. */
    private void documentaryClear(String context, NativePlacement placement, NativeOperation operation,
                                  String reference) throws Exception {
        String capability = operation.operationClass();
        Map<String,Object> r = current("/internal/documentary/v1/restrictions/assess", Map.of(
                "context_id", context, "market", placement.market(),
                "capability", capability, "operation_reference", reference), "documentary_request", "documentary_response");
        if (!context.equals(r.get("context_id"))
                || !placement.operatingOrganisationId().equals(r.get("organisation_id"))
                || !placement.market().equals(r.get("market"))
                || !capability.equals(r.get("capability"))
                || !reference.equals(r.get("operation_reference"))
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
    public boolean currentlyAuthorised(NativeRecord record) {
        try {
            NativeFinancialContextSource placements = placementSource.get();
            NativeFinanceReadiness finance = readiness.get();
            if (operations == null || placements == null || finance == null || record == null
                    || record.transactionName() == null || record.transactionName().isBlank()
                    || record.adClientId() <= 0 || record.recordId() < 0
                    || record.adOrgId() < 0 || record.adOrgId() == 0 && !NativeFinancePolicy.costing(record.table())) {
                return false;
            }
            // Aggregate cost is never an operation: only a cost detail already
            // derived from an authorised root in this transaction covers it.
            if ("M_Cost".equals(record.table())) return derived.costCovered(record);
            NativeOperation operation = operations.classify(record);
            if (operation == null) return false;
            String reference = operation.operationReference();
            if (reference == null) return false;
            NativePlacement placement = placements.currentPlacement(operation);
            if (placement == null || placement.adClientId() != record.adClientId()) return false;
            // Same transaction, same source document, still within its lease by
            // the database clock: the authority already attributed covers this
            // write (an exact-match, bounded PEP reuse; never across transactions).
            if (attribution.hasCurrent(operation)) return derivedRecorded(operation);
            String context = issueCurrentCpContext(placement);
            NativeFinanceAttribution.Decision decision = postingAuthority(context, placement, operation, reference);
            documentaryClear(context, placement, operation, reference);
            NativeFinanceReadiness.FinanceBaseline baseline = finance.currentBaseline(operation, placement);
            if (baseline == null || !placement.legalEntityId().equals(baseline.legalEntityId())) return false;
            // Re-resolve CP just before the immutable same-transaction audit.
            NativeFinanceAttribution.Decision refreshed = postingAuthority(context, placement, operation, reference);
            if (!decision.mandateId().equals(refreshed.mandateId())) return false;
            documentaryClear(context, placement, operation, reference);
            // Until this succeeds in native Trx, even an authorized actor
            // CANNOT enter the financial mutation path.
            attribution.append(operation, placement, refreshed, baseline);
            return derivedRecorded(operation);
        } catch (Exception invalid) {
            // Never leak mandates, financial source data or IAM tokens in logs.
            return false;
        }
    }

    /**
     * A cost detail records that it is a consequence of its now-authorised root
     * (the root's own CP decision, never a costing-specific one) before it may
     * be written; the database refuses the record without that attribution.
     */
    private boolean derivedRecorded(NativeOperation operation) throws Exception {
        if ("M_CostDetail".equals(operation.record().table())) derived.appendCostDetail(operation);
        return true;
    }
}
