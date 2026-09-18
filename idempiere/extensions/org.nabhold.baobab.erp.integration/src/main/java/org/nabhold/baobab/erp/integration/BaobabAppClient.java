package org.nabhold.baobab.erp.integration;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

/**
 * Talks to baobab-app's HTTP API (modules/application/server.py) -- the only way
 * code running inside iDempiere's own JVM reaches the baobab Postgres schema, since
 * it has no direct database access of its own (ADR-ERP-005). One instance per
 * resolver is fine: {@link HttpClient} is thread-safe and reusing it lets the JVM
 * pool connections.
 *
 * <p>baobab-app's /context/resolve* and /mapping/resolve* now require a Baobab
 * IAM-issued workload bearer token (ADR-0014 §111, Gate IAM-10) -- when a {@link
 * WorkloadTokenProvider} is supplied, every request carries one. The no-provider
 * constructors remain only for tests that talk to a fake server with no auth gate;
 * every real resolver ({@code BaobabContextResolver}, {@code
 * BaobabMappingResolver}) always supplies one.
 */
public final class BaobabAppClient {

    private final String baseUrl;
    private final Duration timeout;
    private final HttpClient httpClient;
    private final WorkloadTokenProvider tokenProvider;

    public BaobabAppClient(String baseUrl) {
        this(baseUrl, Duration.ofSeconds(10));
    }

    public BaobabAppClient(String baseUrl, Duration timeout) {
        this(baseUrl, timeout, null);
    }

    public BaobabAppClient(String baseUrl, WorkloadTokenProvider tokenProvider) {
        this(baseUrl, Duration.ofSeconds(10), tokenProvider);
    }

    public BaobabAppClient(String baseUrl, Duration timeout, WorkloadTokenProvider tokenProvider) {
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.timeout = timeout;
        this.httpClient = HttpClient.newBuilder().connectTimeout(timeout).build();
        this.tokenProvider = tokenProvider;
    }

    public static String encodeQueryParam(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    /**
     * @param pathAndQuery e.g. "/context/resolve?tenant_id=...&entity_id=..." with
     *                     query values already encoded via {@link #encodeQueryParam}.
     * @throws BaobabAppNotFoundException on a 404 (no mapping/record for these inputs).
     * @throws BaobabAppClientException   on any other failure to get a usable answer.
     */
    public Map<String, Object> get(String pathAndQuery) throws BaobabAppClientException {
        HttpRequest.Builder requestBuilder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + pathAndQuery))
                .timeout(timeout)
                .header("Accept", "application/json");
        if (tokenProvider != null) {
            requestBuilder.header("Authorization", "Bearer " + tokenProvider.getAccessToken());
        }
        HttpRequest request = requestBuilder.GET().build();

        HttpResponse<String> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new BaobabAppClientException("Could not reach " + request.uri(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new BaobabAppClientException("Interrupted calling " + request.uri(), e);
        }

        Map<String, Object> body;
        try {
            body = (response.body() == null || response.body().isBlank())
                    ? Map.of()
                    : MinimalJson.parseObject(response.body());
        } catch (RuntimeException e) {
            throw new BaobabAppClientException(
                    "Invalid JSON response from " + request.uri() + ": " + e.getMessage(), e);
        }

        if (response.statusCode() == 200) {
            return body;
        }
        String detail = String.valueOf(body.getOrDefault("error", response.body()));
        if (response.statusCode() == 404) {
            throw new BaobabAppNotFoundException(detail);
        }
        throw new BaobabAppClientException(response.statusCode() + " from " + request.uri() + ": " + detail);
    }

    /**
     * @param path e.g. "/outbox/record"; requestBody is serialised via {@link MinimalJson#writeObject}.
     * @throws BaobabAppClientException on any non-2xx response (a POST endpoint that meaningfully
     *         distinguishes 404 doesn't exist yet among this client's current callers).
     */
    public Map<String, Object> post(String path, Map<String, ?> requestBody) throws BaobabAppClientException {
        HttpRequest.Builder requestBuilder = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(timeout)
                .header("Accept", "application/json")
                .header("Content-Type", "application/json");
        if (tokenProvider != null) {
            requestBuilder.header("Authorization", "Bearer " + tokenProvider.getAccessToken());
        }
        HttpRequest request = requestBuilder
                .POST(HttpRequest.BodyPublishers.ofString(MinimalJson.writeObject(requestBody), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new BaobabAppClientException("Could not reach " + request.uri(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new BaobabAppClientException("Interrupted calling " + request.uri(), e);
        }

        Map<String, Object> responseBody;
        try {
            responseBody = (response.body() == null || response.body().isBlank())
                    ? Map.of()
                    : MinimalJson.parseObject(response.body());
        } catch (RuntimeException e) {
            throw new BaobabAppClientException(
                    "Invalid JSON response from " + request.uri() + ": " + e.getMessage(), e);
        }

        if (response.statusCode() >= 200 && response.statusCode() < 300) {
            return responseBody;
        }
        String detail = String.valueOf(responseBody.getOrDefault("error", response.body()));
        throw new BaobabAppClientException(response.statusCode() + " from " + request.uri() + ": " + detail);
    }
}
