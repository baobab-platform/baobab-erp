package org.nabhold.baobab.erp.integration;

import static org.junit.jupiter.api.Assertions.*;
import java.util.Map;
import java.util.List;
import org.junit.jupiter.api.Test;

class ControlPlaneNestedJsonTest {
    @Test
    void parsesActualNestedLegalActorAndArrayEvidence() {
        Map<String,Object> response = MinimalJson.parseObject(
            "{\"provider_permissions_granted\":false,\"legal_actor_resolution\":{"
            + "\"outcome\":\"AUTHORIZED\",\"evidence_references\":[\"source/one\",\"source/two\"]}}");
        assertEquals(false,response.get("provider_permissions_granted"));
        @SuppressWarnings("unchecked")
        Map<String,Object> decision = (Map<String,Object>)response.get("legal_actor_resolution");
        assertEquals("AUTHORIZED",decision.get("outcome"));
        assertEquals(List.of("source/one","source/two"),decision.get("evidence_references"));
    }

    @Test
    void refusesDuplicateAuthoritativeKeysAtAnyDepth() {
        assertThrows(IllegalArgumentException.class, () ->
            MinimalJson.parseObject("{\"provider_permissions_granted\":true,\"provider_permissions_granted\":false}"));
        assertThrows(IllegalArgumentException.class, () ->
            MinimalJson.parseObject("{\"legal_actor_resolution\":{\"outcome\":\"AUTHORIZED\",\"outcome\":\"DENIED\"}}"));
        assertThrows(IllegalArgumentException.class, () ->
            MinimalJson.parseObject("{\"x\":null,\"x\":true}"));
    }
}
