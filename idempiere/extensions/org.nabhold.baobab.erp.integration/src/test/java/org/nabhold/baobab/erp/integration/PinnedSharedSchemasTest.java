package org.nabhold.baobab.erp.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;

class PinnedSharedSchemasTest {
    @Test
    void ownerValidatedSyntheticVectorsAgreeWithNativeJvmAndRestoreTccl() throws Exception {
        var original = Thread.currentThread().getContextClassLoader();
        var hidden = new ClassLoader(null) {};
        try {
            Thread.currentThread().setContextClassLoader(hidden);
            var cases = new ObjectMapper().readTree(getClass().getResourceAsStream("/authority-contract-cases.json"));
            for (var test : cases) {
                byte[] wire = test.get("instance").toString().getBytes(StandardCharsets.UTF_8);
                String name = test.get("contract").asText();
                if (test.get("valid").asBoolean()) {
                    assertDoesNotThrow(() -> {
                        if (name.equals("context_uuid")) PinnedSharedSchemas.require(name, test.get("instance"));
                        else PinnedSharedSchemas.parse(name, wire);
                    }, test.get("name").asText());
                } else {
                    assertThrows(IllegalArgumentException.class, () -> {
                        if (name.equals("context_uuid")) PinnedSharedSchemas.require(name, test.get("instance"));
                        else PinnedSharedSchemas.parse(name, wire);
                    }, test.get("name").asText());
                }
                assertSame(hidden, Thread.currentThread().getContextClassLoader());
            }
        } finally { Thread.currentThread().setContextClassLoader(original); }
    }

    @Test
    void duplicateTrailingCorruptAndOversizedJsonCannotSupplyAuthority() {
        String valid = "{\"context_id\":\"0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b\",\"market\":\"ZA\","
                + "\"capability\":\"accounting.customer-invoice.post\",\"operation_reference\":\"synthetic/123\"}";
        assertDoesNotThrow(() -> PinnedSharedSchemas.parse("documentary_request", valid.getBytes(StandardCharsets.UTF_8)));
        for (String wire : new String[]{valid.replace("\"market\":\"ZA\"", "\"market\":\"ZA\",\"market\":\"ZA\""), valid + "{}", "{\"a\":NaN}"}) {
            assertThrows(IllegalArgumentException.class, () -> PinnedSharedSchemas.parse("documentary_request", wire.getBytes(StandardCharsets.UTF_8)));
        }
        assertThrows(IllegalArgumentException.class, () -> PinnedSharedSchemas.parse("context_request", new byte[]{'{','"','x','"',':','"',(byte)0xC3,'(', '"','}'}));
        assertThrows(IllegalArgumentException.class, () -> PinnedSharedSchemas.parse("context_request", new byte[16385]));
        assertThrows(IllegalArgumentException.class, () -> PinnedSharedSchemas.require("unregistered", java.util.Map.of()));
    }
}
