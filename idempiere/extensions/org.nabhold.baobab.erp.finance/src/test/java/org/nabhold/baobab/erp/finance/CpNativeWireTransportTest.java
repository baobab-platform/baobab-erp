package org.nabhold.baobab.erp.finance;

import com.sun.net.httpserver.HttpServer;
import java.lang.reflect.InvocationTargetException;
import java.net.InetSocketAddress;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import static org.junit.jupiter.api.Assertions.*;

/** Synthetic transport proof only: no native company, IAM standing or permit. */
class CpNativeWireTransportTest {
    private CpNativeFinancialAuthority client(HttpServer server, AtomicInteger tokens) {
        return new CpNativeFinancialAuthority("http://127.0.0.1:" + server.getAddress().getPort(),
                () -> { tokens.incrementAndGet(); return "synthetic-token"; }, true, null, null,
                new NativeFinanceAttribution(name -> { throw new AssertionError("No native attribution in wire test"); }));
    }
    private Object current(CpNativeFinancialAuthority client, String route) throws Exception {
        // Keep production transport private; exercise the real HTTP implementation.
        var method = CpNativeFinancialAuthority.class.getDeclaredMethod("current", String.class, Map.class, String.class, String.class);
        method.setAccessible(true);
        try { return method.invoke(client, route, Map.of(), "context_request", "context_response"); }
        catch (InvocationTargetException wrapped) {
            if (wrapped.getCause() instanceof Exception cause) throw cause;
            throw new AssertionError(wrapped.getCause());
        }
    }
    @Test @Timeout(10)
    void partialBodyCannotEscapeTheCompleteResponseDeadline() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        CountDownLatch release = new CountDownLatch(1);
        server.createContext("/slow", exchange -> {
            exchange.sendResponseHeaders(200, 100);
            exchange.getResponseBody().write('{');
            exchange.getResponseBody().flush();
            try { release.await(); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
            finally { exchange.close(); }
        });
        server.start();
        try {
            Exception failed = assertThrows(Exception.class, () -> current(client(server, new AtomicInteger()), "/slow"));
            assertTrue(failed instanceof TimeoutException || failed instanceof ExecutionException
                    && failed.getCause() instanceof java.net.http.HttpTimeoutException);
        } finally { release.countDown(); server.stop(0); }
    }
    @Test @Timeout(10)
    void oversizedBodyIsCancelledBeforeParsing() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/large", exchange -> {
            byte[] bytes = new byte[16385];
            exchange.sendResponseHeaders(200, bytes.length);
            try { exchange.getResponseBody().write(bytes); }
            finally { exchange.close(); }
        });
        server.start();
        try {
            var failed = assertThrows(ExecutionException.class, () -> current(client(server, new AtomicInteger()), "/large"));
            assertInstanceOf(IllegalStateException.class, failed.getCause());
        } finally { server.stop(0); }
    }
    @Test @Timeout(10)
    void redirectCannotForwardWorkloadCredentials() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicInteger leaked = new AtomicInteger();
        server.createContext("/redirect", exchange -> {
            exchange.getResponseHeaders().add("Location", "http://127.0.0.1:" + server.getAddress().getPort() + "/other");
            exchange.sendResponseHeaders(302, -1); exchange.close();
        });
        server.createContext("/other", exchange -> {
            leaked.incrementAndGet(); exchange.sendResponseHeaders(200, -1); exchange.close();
        });
        server.start();
        try {
            assertThrows(IllegalStateException.class, () -> current(client(server, new AtomicInteger()), "/redirect"));
            assertEquals(0, leaked.get());
        } finally { server.stop(0); }
    }
}
