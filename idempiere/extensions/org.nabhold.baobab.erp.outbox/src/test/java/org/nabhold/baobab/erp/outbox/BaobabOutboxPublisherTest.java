package org.nabhold.baobab.erp.outbox;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.nabhold.baobab.erp.integration.BaobabAppClient;
import org.nabhold.baobab.erp.outbox.OutboxPublisher.OutboxPublicationException;

/**
 * Exercises BaobabOutboxPublisher against a real local HTTP server reproducing
 * baobab-app's /outbox/record response shape, matching
 * BaobabContextResolverTest's own style.
 */
class BaobabOutboxPublisherTest {

    private HttpServer server;
    private BaobabOutboxPublisher publisher;
    private final AtomicReference<String> lastRequestBody = new AtomicReference<>();

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/outbox/record", exchange -> {
            String body = readBody(exchange.getRequestBody());
            lastRequestBody.set(body);
            if (body.contains("\"tenant_id\":\"unreachable-tenant\"")) {
                respond(exchange, 500, "{\"error\": \"boom\"}");
            } else {
                respond(exchange, 202, "{\"status\": \"accepted\"}");
            }
        });
        server.start();
        BaobabAppClient client = new BaobabAppClient("http://127.0.0.1:" + server.getAddress().getPort());
        publisher = new BaobabOutboxPublisher(client);
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    private static String readBody(InputStream input) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        input.transferTo(buffer);
        return buffer.toString(StandardCharsets.UTF_8);
    }

    private static void respond(com.sun.net.httpserver.HttpExchange exchange, int status, String body)
            throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    @Test
    void publishesEventOverHttp() throws Exception {
        publisher.publish(
                "erp.sales-order.accepted.v1", "zuribeans-ug", "zuribeans-ug-legal", "corr-1",
                Map.of("erp_order_native_id", 42));
        String body = lastRequestBody.get();
        assertTrue(body.contains("\"event_type\":\"erp.sales-order.accepted.v1\""));
        assertTrue(body.contains("\"tenant_id\":\"zuribeans-ug\""));
        assertTrue(body.contains("\"correlation_id\":\"corr-1\""));
        assertTrue(body.contains("\"erp_order_native_id\":42"));
    }

    @Test
    void blankEventTypeFailsClosedWithoutCallingTheNetwork() {
        assertThrows(OutboxPublicationException.class,
                () -> publisher.publish("", "zuribeans-ug", "zuribeans-ug-legal", "corr-1", Map.of()));
        assertEquals(null, lastRequestBody.get());
    }

    @Test
    void serverErrorFailsClosedNotSilently() {
        OutboxPublicationException exception = assertThrows(OutboxPublicationException.class,
                () -> publisher.publish(
                        "erp.sales-order.accepted.v1", "unreachable-tenant", "legal", "corr-1", Map.of()));
        assertTrue(exception.getMessage().contains("Could not record event"));
    }

    @Test
    void unreachableBackendFailsClosedNotSilently() {
        BaobabOutboxPublisher unreachable = new BaobabOutboxPublisher(new BaobabAppClient("http://127.0.0.1:1"));
        OutboxPublicationException exception = assertThrows(OutboxPublicationException.class,
                () -> unreachable.publish("erp.sales-order.accepted.v1", "zuribeans-ug", "legal", "corr-1", Map.of()));
        assertTrue(exception.getMessage().contains("Could not record event"));
    }
}
