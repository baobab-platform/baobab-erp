package org.nabhold.baobab.erp.integration;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Small compatibility parser for legacy application-service responses, including
 * nested objects and arrays. It is not JSON Schema validation. Consequential CP
 * facts use {@link PinnedSharedSchemas}, which enforces the immutable Shared wire
 * contracts and strict JSON syntax before native financial authority checks.
 * Numbers are returned as {@link Long} or {@link Double}.
 */
public final class MinimalJson {

    private final String text;
    private int position;

    private MinimalJson(String text) {
        this.text = text;
    }

    /**
     * Serialises a flat-ish JSON object: String, Number, Boolean, null values, and
     * one level of nested {@code Map<String, Object>} (enough for the outbox event
     * payloads this bundle sends -- e.g. {@code {"table": "C_Order", "record_id": 42}}).
     * Not a general JSON writer; deliberately narrow, matching {@link #parseObject}'s
     * own scope, so this bundle needs no external JSON dependency.
     */
    static String writeObject(Map<String, ?> value) {
        StringBuilder builder = new StringBuilder();
        writeObjectInto(builder, value);
        return builder.toString();
    }

    private static void writeObjectInto(StringBuilder builder, Map<String, ?> value) {
        builder.append('{');
        boolean first = true;
        for (Map.Entry<String, ?> entry : value.entrySet()) {
            if (!first) {
                builder.append(',');
            }
            first = false;
            writeString(builder, entry.getKey());
            builder.append(':');
            writeValue(builder, entry.getValue());
        }
        builder.append('}');
    }

    private static void writeValue(StringBuilder builder, Object value) {
        if (value == null) {
            builder.append("null");
        } else if (value instanceof String s) {
            writeString(builder, s);
        } else if (value instanceof Number || value instanceof Boolean) {
            builder.append(value);
        } else if (value instanceof Map<?, ?> nested) {
            @SuppressWarnings("unchecked")
            Map<String, ?> typed = (Map<String, ?>) nested;
            writeObjectInto(builder, typed);
        } else {
            throw new IllegalArgumentException(
                    "Unsupported value type for MinimalJson.writeObject: " + value.getClass());
        }
    }

    private static void writeString(StringBuilder builder, String value) {
        builder.append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"' -> builder.append("\\\"");
                case '\\' -> builder.append("\\\\");
                case '\n' -> builder.append("\\n");
                case '\t' -> builder.append("\\t");
                case '\r' -> builder.append("\\r");
                default -> {
                    if (c < 0x20) {
                        builder.append(String.format("\\u%04x", (int) c));
                    } else {
                        builder.append(c);
                    }
                }
            }
        }
        builder.append('"');
    }

    public static Map<String, Object> parseObject(String text) {
        MinimalJson parser = new MinimalJson(text);
        parser.skipWhitespace();
        Map<String, Object> result = parser.readObject();
        parser.skipWhitespace();
        if (!parser.atEnd()) {
            throw new IllegalArgumentException("Unexpected trailing content in JSON: " + text);
        }
        return result;
    }

    private Map<String, Object> readObject() {
        expect('{');
        Map<String, Object> result = new LinkedHashMap<>();
        skipWhitespace();
        if (peek() == '}') {
            position++;
            return result;
        }
        while (true) {
            skipWhitespace();
            String key = readString();
            skipWhitespace();
            expect(':');
            skipWhitespace();
            Object value = readValue();
            if (result.containsKey(key)) {
                throw new IllegalArgumentException("Duplicate JSON property");
            }
            result.put(key, value);
            skipWhitespace();
            char next = peek();
            if (next == ',') {
                position++;
                continue;
            }
            if (next == '}') {
                position++;
                break;
            }
            throw new IllegalArgumentException("Expected ',' or '}' at position " + position + " in: " + text);
        }
        return result;
    }

    private Object readValue() {
        char c = peek();
        if (c == '{') {
            return readObject();
        }
        if (c == '[') {
            return readArray();
        }
        if (c == '"') {
            return readString();
        }
        if (c == '-' || Character.isDigit(c)) {
            return readNumber();
        }
        if (text.startsWith("true", position)) {
            position += 4;
            return Boolean.TRUE;
        }
        if (text.startsWith("false", position)) {
            position += 5;
            return Boolean.FALSE;
        }
        if (text.startsWith("null", position)) {
            position += 4;
            return null;
        }
        throw new IllegalArgumentException("Unexpected value at position " + position + " in: " + text);
    }

    private java.util.List<Object> readArray() {
        expect('[');
        java.util.List<Object> result = new java.util.ArrayList<>();
        skipWhitespace();
        if (!atEnd() && peek() == ']') {
            position++;
            return result;
        }
        while (true) {
            skipWhitespace();
            result.add(readValue());
            skipWhitespace();
            char next = peek();
            if (next == ']') {
                position++;
                return result;
            }
            expect(',');
        }
    }

    private String readString() {
        expect('"');
        StringBuilder builder = new StringBuilder();
        while (true) {
            char c = next();
            if (c == '"') {
                break;
            }
            if (c == '\\') {
                char escaped = next();
                switch (escaped) {
                    case '"' -> builder.append('"');
                    case '\\' -> builder.append('\\');
                    case '/' -> builder.append('/');
                    case 'n' -> builder.append('\n');
                    case 't' -> builder.append('\t');
                    case 'r' -> builder.append('\r');
                    case 'b' -> builder.append('\b');
                    case 'f' -> builder.append('\f');
                    case 'u' -> {
                        String hex = text.substring(position, position + 4);
                        position += 4;
                        builder.append((char) Integer.parseInt(hex, 16));
                    }
                    default -> throw new IllegalArgumentException("Unknown escape '\\" + escaped + "'");
                }
            } else {
                builder.append(c);
            }
        }
        return builder.toString();
    }

    private Object readNumber() {
        int start = position;
        if (peek() == '-') {
            position++;
        }
        boolean isFloatingPoint = false;
        while (!atEnd() && (Character.isDigit(peek()) || peek() == '.' || peek() == 'e' || peek() == 'E'
                || peek() == '+' || peek() == '-')) {
            if (peek() == '.' || peek() == 'e' || peek() == 'E') {
                isFloatingPoint = true;
            }
            position++;
        }
        String number = text.substring(start, position);
        return isFloatingPoint ? (Object) Double.parseDouble(number) : (Object) Long.parseLong(number);
    }

    private void skipWhitespace() {
        while (!atEnd() && Character.isWhitespace(peek())) {
            position++;
        }
    }

    private void expect(char c) {
        if (atEnd() || peek() != c) {
            throw new IllegalArgumentException("Expected '" + c + "' at position " + position + " in: " + text);
        }
        position++;
    }

    private char peek() {
        if (atEnd()) {
            throw new IllegalArgumentException("Unexpected end of JSON input: " + text);
        }
        return text.charAt(position);
    }

    private char next() {
        if (atEnd()) {
            throw new IllegalArgumentException("Unexpected end of JSON input: " + text);
        }
        return text.charAt(position++);
    }

    private boolean atEnd() {
        return position >= text.length();
    }
}
