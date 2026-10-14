package org.nabhold.baobab.erp.finance;

import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.function.BiFunction;

/**
 * Synthetic JDBC for unit tests only: queries answer from a handler, updates
 * are captured. Real PostgreSQL behaviour is proven by the Gate B job.
 */
final class FakeJdbc {
    final List<Map<Integer, Object>> updates = new ArrayList<>();
    final List<String> queries = new ArrayList<>();
    int commits;
    boolean autoCommit;
    /** (sql, parameters) -> rows; each row is the column values in order. */
    BiFunction<String, Map<Integer, Object>, List<Object[]>> answer = (sql, params) -> List.of();

    Connection connection() {
        return (Connection) Proxy.newProxyInstance(getClass().getClassLoader(), new Class<?>[]{Connection.class},
                (o, m, a) -> switch (m.getName()) {
                    case "getAutoCommit" -> autoCommit;
                    case "prepareStatement" -> statement((String) a[0]);
                    case "commit", "rollback", "close" -> { commits++; yield null; }
                    default -> null;
                });
    }

    private PreparedStatement statement(String sql) {
        Map<Integer, Object> params = new TreeMap<>();
        return (PreparedStatement) Proxy.newProxyInstance(getClass().getClassLoader(),
                new Class<?>[]{PreparedStatement.class}, (o, m, a) -> {
                    String name = m.getName();
                    if (name.startsWith("set") && a != null && a.length == 2) {
                        params.put((Integer) a[0], a[1]);
                        return null;
                    }
                    return switch (name) {
                        case "executeUpdate" -> { updates.add(params); yield 1; }
                        case "executeQuery" -> { queries.add(sql); yield results(answer.apply(sql, params)); }
                        default -> null;
                    };
                });
    }

    private ResultSet results(List<Object[]> rows) {
        int[] cursor = {-1};
        return (ResultSet) Proxy.newProxyInstance(getClass().getClassLoader(), new Class<?>[]{ResultSet.class},
                (o, m, a) -> switch (m.getName()) {
                    case "next" -> ++cursor[0] < rows.size();
                    case "getString" -> {
                        Object v = rows.get(cursor[0])[(Integer) a[0] - 1];
                        yield v == null ? null : v.toString();
                    }
                    case "getInt" -> ((Number) rows.get(cursor[0])[(Integer) a[0] - 1]).intValue();
                    case "getBoolean" -> (Boolean) rows.get(cursor[0])[(Integer) a[0] - 1];
                    default -> null;
                });
    }
}
