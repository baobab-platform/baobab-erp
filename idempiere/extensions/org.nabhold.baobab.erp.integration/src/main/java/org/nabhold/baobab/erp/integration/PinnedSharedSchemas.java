package org.nabhold.baobab.erp.integration;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SchemaRegistryConfig;
import com.networknt.schema.SpecificationVersion;

import java.io.InputStream;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * P0-04A / ADR-ERP-005: exact Shared wire schemas at the native JVM boundary.
 * Package-owned resources and a cached registry enforce formats and closed
 * shapes without downloading schemas. Valid shape is NOT permission: native
 * context/actor/freshness/readiness and atomic attribution remain mandatory.
 * Dependencies are shaded privately to avoid iDempiere Jackson wiring drift.
 */
public final class PinnedSharedSchemas {
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(64)
                    .maxStringLength(16384).build()).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    private static final Map<String, Schema> VALIDATORS = withOwnLoader(PinnedSharedSchemas::load);

    private PinnedSharedSchemas() {}

    private static <T> T withOwnLoader(Supplier<T> task) {
        // Networknt's bundled meta-schema loader may consult TCCL under OSGi.
        // Use this bundle's loader only for validation and ALWAYS restore the
        // caller's thread context; never mutate a process-global class loader.
        Thread thread = Thread.currentThread();
        ClassLoader previous = thread.getContextClassLoader();
        try {
            thread.setContextClassLoader(PinnedSharedSchemas.class.getClassLoader());
            return task.get();
        } finally {
            thread.setContextClassLoader(previous);
        }
    }

    private static byte[] resource(String name) throws Exception {
        try (InputStream input = PinnedSharedSchemas.class.getResourceAsStream("/shared-contracts/" + name)) {
            if (input == null) throw new IllegalStateException("Pinned Shared resource unavailable");
            return input.readAllBytes();
        }
    }

    private static Map<String, Schema> load() {
        try {
            JsonNode manifest = JSON.readTree(resource("provenance.json"));
            Map<String, String> resources = new LinkedHashMap<>();
            var files = manifest.get("files").fields();
            while (files.hasNext()) {
                var file = files.next();
                byte[] bytes = resource(file.getKey());
                String hash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
                if (!hash.equals(file.getValue().asText())) {
                    throw new IllegalStateException("Pinned Shared resource integrity failed");
                }
                resources.put(JSON.readTree(bytes).get("$id").asText(), new String(bytes, java.nio.charset.StandardCharsets.UTF_8));
            }
            SchemaRegistry registry = SchemaRegistry.withDefaultDialect(SpecificationVersion.DRAFT_2020_12,
                    builder -> builder.schemas(resources)
                            .nodeReader(reader -> reader.jsonMapper(JSON))
                            .schemaLoader(loader -> loader.fetchRemoteResources(false))
                            .schemaRegistryConfig(SchemaRegistryConfig.builder().formatAssertionsEnabled(true).build()));
            Map<String, Schema> validators = new LinkedHashMap<>();
            var entries = manifest.get("entries").fields();
            while (entries.hasNext()) {
                var entry = entries.next();
                validators.put(entry.getKey(), registry.getSchema(SchemaLocation.of(entry.getValue().asText())));
            }
            return Map.copyOf(validators);
        } catch (Exception invalid) {
            throw new IllegalStateException("Pinned Shared validators unavailable", invalid);
        }
    }

    private static void requireNode(String name, JsonNode value) {
        withOwnLoader(() -> {
            Schema schema = VALIDATORS.get(name);
            if (schema == null || !schema.validate(value).isEmpty()) {
                // Never expose tokens, evidence references or input values in an error.
                throw new IllegalArgumentException("Invalid pinned Shared wire contract: " + name);
            }
            return null;
        });
    }

    public static void require(String name, Object value) {
        requireNode(name, JSON.valueToTree(value));
    }

    public static Map<String, Object> parse(String name, byte[] bytes) {
        if (bytes.length > 16384) throw new IllegalArgumentException("Oversized CP wire fact");
        try {
            JsonNode node = JSON.readTree(bytes);
            requireNode(name, node);
            return JSON.convertValue(node, new TypeReference<Map<String, Object>>() {});
        } catch (Exception invalid) {
            throw new IllegalArgumentException("Invalid CP wire fact");
        }
    }

    public static String encode(Object value) {
        try { return JSON.writeValueAsString(value); }
        catch (Exception invalid) { throw new IllegalArgumentException("Invalid CP wire request", invalid); }
    }

    /** Build/conformance probe only; no endpoint, admission or native permit. */
    public static void check() {
        for (String name : VALIDATORS.keySet()) {
            try { require(name, Map.of()); }
            catch (IllegalArgumentException denied) { continue; }
            // Resolve request legitimately allows an empty body.
            if (!name.equals("context_request")) throw new IllegalStateException("Empty fact accepted");
        }
        System.out.println("Pinned Shared JVM resources and validators verified");
    }

    /** Run from the packaged JAR to verify private dependencies and OSGi-like
     * resource visibility, or compare synthetic owner-validated wire vectors. */
    public static void main(String[] args) throws Exception {
        Thread thread = Thread.currentThread();
        ClassLoader previous = thread.getContextClassLoader();
        try {
            thread.setContextClassLoader(new ClassLoader(null) {});
            if (args.length == 1 && args[0].equals("--self-test")) {
                var jar = PinnedSharedSchemas.class.getProtectionDomain().getCodeSource().getLocation();
                try (var isolated = new URLClassLoader(new java.net.URL[]{jar}, ClassLoader.getPlatformClassLoader())) {
                    Class.forName(PinnedSharedSchemas.class.getName(), true, isolated).getMethod("check").invoke(null);
                }
            } else if (args.length == 2 && args[0].equals("--conformance")) {
                JsonNode cases = JSON.readTree(Path.of(args[1]).toFile());
                for (JsonNode test : cases) {
                    boolean valid;
                    try { requireNode(test.get("contract").asText(), test.get("instance")); valid = true; }
                    catch (IllegalArgumentException denied) { valid = false; }
                    if (valid != test.get("valid").asBoolean()) {
                        throw new IllegalStateException("JVM wire conformance mismatch: " + test.get("name").asText());
                    }
                }
                System.out.println("JVM wire vectors verified: " + cases.size());
            } else throw new IllegalArgumentException("Expected --self-test or --conformance <synthetic vectors>");
        } finally { thread.setContextClassLoader(previous); }
    }
}
