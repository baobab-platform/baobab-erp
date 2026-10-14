package org.nabhold.baobab.erp.finance;

import java.util.function.Function;

/**
 * The native row a synchronous ModelValidator callback is about to change,
 * read from the iDempiere PO itself. Column values are the PO's own, never a
 * caller header, JVM property or UI field outside the record.
 */
public record NativeRecord(String table, int adClientId, int adOrgId, int recordId,
                           String action, String transactionName,
                           Function<String, Object> column) {
    public Object value(String name) {
        try {
            return column == null ? null : column.apply(name);
        } catch (RuntimeException unreadable) {
            return null;
        }
    }

    public int intValue(String name) {
        Object v = value(name);
        if (v instanceof Number n) return n.intValue();
        if (v instanceof String s) {
            try { return Integer.parseInt(s.trim()); } catch (NumberFormatException ignored) { return -1; }
        }
        return -1;
    }

    /** iDempiere returns Boolean for Y/N columns; tolerate the raw 'Y'. */
    public Boolean flag(String name) {
        Object v = value(name);
        if (v instanceof Boolean b) return b;
        if (v instanceof String s) return "Y".equals(s) ? Boolean.TRUE : "N".equals(s) ? Boolean.FALSE : null;
        return null;
    }
}
