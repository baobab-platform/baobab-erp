package org.nabhold.baobab.erp.integration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Exercises WorkloadTokenProvider against a real local HTTP server standing in for
 * Baobab IAM's token endpoint -- not a mock.
 */
class WorkloadTokenProviderTest {

    private HttpServer server;
    private AtomicInteger tokenRequests;
    private AtomicReference<String> postedForm;
    private String tokenUrl;

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        tokenRequests = new AtomicInteger();
        postedForm = new AtomicReference<>();
        server.createContext("/token", exchange -> {
            tokenRequests.incrementAndGet();
            postedForm.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            respond(exchange, 200, "{\"access_token\": \"tok-" + tokenRequests.get()
                    + "\", \"expires_in\": 300, \"token_type\": \"Bearer\"}");
        });
        server.createContext("/token-immediate-expiry", exchange -> {
            tokenRequests.incrementAndGet();
            respond(exchange, 200, "{\"access_token\": \"tok-" + tokenRequests.get()
                    + "\", \"expires_in\": 0}");
        });
        server.createContext("/token-error", exchange -> respond(exchange, 401, "{\"error\": \"invalid_client\"}"));
        server.createContext("/token-malformed", exchange -> respond(exchange, 200, "not json"));
        server.createContext("/token-no-access-token", exchange -> respond(exchange, 200, "{\"token_type\": \"Bearer\"}"));
        server.start();
        tokenUrl = "http://127.0.0.1:" + server.getAddress().getPort() + "/token";
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    private static void respond(com.sun.net.httpserver.HttpExchange exchange, int status, String body)
            throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    @Test
    void fetchesAndReturnsAnAccessToken() throws Exception {
        WorkloadTokenProvider provider = new WorkloadTokenProvider(tokenUrl, "baobab-erp-workload", "secret", "erp:integrate");
        assertEquals("tok-1", provider.getAccessToken());
    }

    @Test
    void nativeCpTokenRequestBindsAnExplicitAudience() throws Exception {
        WorkloadTokenProvider provider = new WorkloadTokenProvider(tokenUrl,
                "baobab-erp-legal-actor-assessor-staging", "secret",
                "context:resolve erp-posting-authority:resolve", "baobab-control-plane");
        assertEquals("tok-1", provider.getAccessToken());
        assertTrue(postedForm.get().contains("audience=baobab-control-plane"),
                "Hydra must receive CP as the requested resource audience");
        assertTrue(postedForm.get().contains("scope=context%3Aresolve+erp-posting-authority%3Aresolve"));
    }

    @Test
    void reusesACachedTokenUntilNearExpiry() throws Exception {
        WorkloadTokenProvider provider = new WorkloadTokenProvider(tokenUrl, "baobab-erp-workload", "secret", "erp:integrate");
        String first = provider.getAccessToken();
        String second = provider.getAccessToken();
        assertEquals(first, second);
        assertEquals(1, tokenRequests.get());
    }

    @Test
    void refetchesOnceTheCachedTokenIsNearExpiry() throws Exception {
        String immediateExpiryUrl = tokenUrl.replace("/token", "/token-immediate-expiry");
        WorkloadTokenProvider provider =
                new WorkloadTokenProvider(immediateExpiryUrl, "baobab-erp-workload", "secret", "erp:integrate");
        provider.getAccessToken();
        provider.getAccessToken();
        assertTrue(tokenRequests.get() >= 2, "expected a second fetch once the first token's TTL elapsed");
    }

    @Test
    void raisesOnAnErrorResponse() {
        String errorUrl = tokenUrl.replace("/token", "/token-error");
        WorkloadTokenProvider provider = new WorkloadTokenProvider(errorUrl, "baobab-erp-workload", "secret", "erp:integrate");
        assertThrows(BaobabAppClientException.class, provider::getAccessToken);
    }

    @Test
    void raisesOnMalformedJson() {
        String malformedUrl = tokenUrl.replace("/token", "/token-malformed");
        WorkloadTokenProvider provider = new WorkloadTokenProvider(malformedUrl, "baobab-erp-workload", "secret", "erp:integrate");
        assertThrows(BaobabAppClientException.class, provider::getAccessToken);
    }

    @Test
    void raisesWhenResponseHasNoAccessToken() {
        String noTokenUrl = tokenUrl.replace("/token", "/token-no-access-token");
        WorkloadTokenProvider provider = new WorkloadTokenProvider(noTokenUrl, "baobab-erp-workload", "secret", "erp:integrate");
        assertThrows(BaobabAppClientException.class, provider::getAccessToken);
    }
}
