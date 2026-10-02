package org.nabhold.baobab.erp.integration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.Map;
import org.junit.jupiter.api.Test;

class MinimalJsonTest {

    @Test
    void parsesIntegerFields() {
        Map<String, Object> result = MinimalJson.parseObject("{\"ad_client_id\": 1000, \"ad_org_id\": 1}");
        assertEquals(1000L, result.get("ad_client_id"));
        assertEquals(1L, result.get("ad_org_id"));
    }

    @Test
    void parsesStringAndMixedFields() {
        Map<String, Object> result = MinimalJson.parseObject("{\"table\": \"C_BPartner\", \"record_id\": 1001}");
        assertEquals("C_BPartner", result.get("table"));
        assertEquals(1001L, result.get("record_id"));
    }

    @Test
    void parsesEscapedStrings() {
        Map<String, Object> result = MinimalJson.parseObject("{\"error\": \"no mapping for \\\"Party\\\"\"}");
        assertEquals("no mapping for \"Party\"", result.get("error"));
    }

    @Test
    void parsesNullAndBoolean() {
        Map<String, Object> result = MinimalJson.parseObject("{\"a\": null, \"b\": true, \"c\": false}");
        assertNull(result.get("a"));
        assertEquals(Boolean.TRUE, result.get("b"));
        assertEquals(Boolean.FALSE, result.get("c"));
    }

    @Test
    void parsesEmptyObject() {
        assertEquals(Map.of(), MinimalJson.parseObject("{}"));
    }

    @Test
    void parsesFloatingPointNumbers() {
        Map<String, Object> result = MinimalJson.parseObject("{\"rate\": 7.5}");
        assertEquals(7.5, result.get("rate"));
    }

    @Test
    void rejectsTrailingGarbage() {
        assertThrows(IllegalArgumentException.class, () -> MinimalJson.parseObject("{}garbage"));
    }

    @Test
    void rejectsMalformedObject() {
        assertThrows(IllegalArgumentException.class, () -> MinimalJson.parseObject("{\"a\": 1"));
    }

    @Test
    void parsesAFlatProblemDocumentAndReadsItsDetail() {
        String problem = "{\"type\": \"https://contracts.baobab-platform.com/problems/erp/not-found\","
                + " \"title\": \"Resource not found\", \"status\": 404, \"code\": \"ERP_RESOURCE_NOT_FOUND\","
                + " \"correlation_id\": \"0b9a7c1e-3b0e-4a57-9d4a-2a1d6a3f7e10\", \"retryable\": false,"
                + " \"detail\": \"no active mapping\"}";
        Map<String, Object> result = MinimalJson.parseObject(problem);
        assertEquals(404L, result.get("status"));
        assertEquals("no active mapping", BaobabAppClient.problemDetail(result, problem));
    }

    @Test
    void problemDetailFallsBackToTitleThenLegacyErrorThenRawBody() {
        assertEquals("Resource not found",
                BaobabAppClient.problemDetail(Map.of("title", "Resource not found"), "raw"));
        assertEquals("legacy", BaobabAppClient.problemDetail(Map.of("error", "legacy"), "raw"));
        assertEquals("raw", BaobabAppClient.problemDetail(Map.of(), "raw"));
    }
}
