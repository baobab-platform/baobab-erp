package org.nabhold.baobab.erp.integration;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpRequest.BodyPublishers;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;

/**
 * Obtains and caches a Baobab IAM client-credentials workload token for
 * baobab-erp-workload, attached by {@link BaobabAppClient} as the Authorization
 * header on every call to baobab-app's HTTP boundary -- baobab-app now requires one
 * (ADR-0014 §111, Gate IAM-10) rather than trusting network location alone. Tokens
 * are cached until shortly before their own expiry rather than fetched per request.
 */
public final class WorkloadTokenProvider {

    private static final Duration EXPIRY_MARGIN = Duration.ofSeconds(30);
    private static final long DEFAULT_EXPIRES_IN_SECONDS = 300;

    private final String tokenUrl;
    private final String clientId;
    private final String clientSecret;
    private final String scope;
    private final String audience;
    private final HttpClient httpClient;

    private volatile String cachedToken;
    private volatile Instant cachedTokenExpiry = Instant.EPOCH;

    public WorkloadTokenProvider(String tokenUrl, String clientId, String clientSecret, String scope) {
        this(tokenUrl, clientId, clientSecret, scope, null);
    }

    /**
     * A protected resource audience must be requested explicitly from Ory
     * Hydra. The registered client's default audience is not assumed to be
     * the Control Plane audience (ADR-IAM-0007 / DEV-09).
     */
    public WorkloadTokenProvider(String tokenUrl, String clientId, String clientSecret,
                                 String scope, String audience) {
        this.audience = audience;
        this.tokenUrl = tokenUrl;
        this.clientId = clientId;
        this.clientSecret = clientSecret;
        this.scope = scope;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    }

    public synchronized String getAccessToken() throws BaobabAppClientException {
        Instant now = Instant.now();
        if (cachedToken != null && now.isBefore(cachedTokenExpiry.minus(EXPIRY_MARGIN))) {
            return cachedToken;
        }

        String form = "grant_type=client_credentials"
                + "&client_id=" + urlEncode(clientId)
                + "&client_secret=" + urlEncode(clientSecret)
                + "&scope=" + urlEncode(scope)
                + (audience == null ? "" : "&audience=" + urlEncode(audience));
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(tokenUrl))
                .timeout(Duration.ofSeconds(10))
                .header("Content-Type", "application/x-www-form-urlencoded")
                .POST(BodyPublishers.ofString(form))
                .build();

        HttpResponse<String> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new BaobabAppClientException("Could not reach Baobab IAM token endpoint " + tokenUrl, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new BaobabAppClientException("Interrupted fetching workload token from " + tokenUrl, e);
        }
        if (response.statusCode() != 200) {
            throw new BaobabAppClientException(
                    "Baobab IAM token endpoint returned " + response.statusCode() + ": " + response.body());
        }

        Map<String, Object> body;
        try {
            body = MinimalJson.parseObject(response.body());
        } catch (RuntimeException e) {
            throw new BaobabAppClientException("Invalid JSON from Baobab IAM token endpoint: " + e.getMessage(), e);
        }
        Object accessToken = body.get("access_token");
        if (!(accessToken instanceof String) || ((String) accessToken).isBlank()) {
            throw new BaobabAppClientException("Baobab IAM token response had no access_token");
        }

        long expiresInSeconds = DEFAULT_EXPIRES_IN_SECONDS;
        Object expiresIn = body.get("expires_in");
        if (expiresIn instanceof Number) {
            expiresInSeconds = ((Number) expiresIn).longValue();
        }

        cachedToken = (String) accessToken;
        cachedTokenExpiry = now.plusSeconds(expiresInSeconds);
        return cachedToken;
    }

    private static String urlEncode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }
}
