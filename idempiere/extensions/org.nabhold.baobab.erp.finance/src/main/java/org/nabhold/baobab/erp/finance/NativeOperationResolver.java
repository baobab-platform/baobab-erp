package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Map;
import java.util.Set;

/**
 * ERP's table-to-operation policy (ADR-ERP-022): classifies a protected native
 * write into exactly one Shared erp/v2 operation class and its source document,
 * or returns null so the write is DENIED in a protected runtime.
 *
 * Purchase-side documents (vendor invoices, purchase orders, material
 * receipts) and accounting configuration (schema, chart, tax, costing, bank
 * accounts) have no catalogued class yet and therefore stay denied.
 */
final class NativeOperationResolver {
    /** Header tables: the governed source documents and their class. */
    private static final Map<String, String> HEADERS = Map.of(
            "GL_Journal", NativeOperation.GL_JOURNAL,
            "C_Invoice", NativeOperation.CUSTOMER_INVOICE,
            "C_Payment", NativeOperation.PAYMENT,
            "C_BankStatement", NativeOperation.PAYMENT,
            "C_Cash", NativeOperation.PAYMENT,
            "C_AllocationHdr", NativeOperation.ALLOCATION,
            "M_InOut", NativeOperation.SHIPMENT,
            "C_Order", NativeOperation.SALES_ORDER);
    /** Line tables and the header they belong to. */
    private static final Map<String, String> LINES = Map.of(
            "GL_JournalLine", "GL_Journal",
            "C_InvoiceLine", "C_Invoice",
            "C_BankStatementLine", "C_BankStatement",
            "C_CashLine", "C_Cash",
            "C_AllocationLine", "C_AllocationHdr",
            "M_InOutLine", "M_InOut",
            "C_OrderLine", "C_Order");
    /** Headers that are governed only on the sales side. */
    private static final Set<String> SALES_SIDE_ONLY = Set.of("C_Invoice", "M_InOut", "C_Order");

    private final NativeConnections connections;

    NativeOperationResolver(NativeConnections connections) {
        this.connections = connections;
    }

    NativeOperation classify(NativeRecord record) throws Exception {
        String table = record.table();
        if (HEADERS.containsKey(table)) {
            if (SALES_SIDE_ONLY.contains(table) && !Boolean.TRUE.equals(record.flag("IsSOTrx"))) {
                return null;
            }
            return new NativeOperation(HEADERS.get(table), table, Math.max(record.recordId(), 0), record);
        }
        String header = LINES.get(table);
        if (header != null) {
            int headerId = record.intValue(header + "_ID");
            return headerId > 0 ? sourceDocument(header, headerId, record) : null;
        }
        if ("Fact_Acct".equals(table)) {
            int tableId = record.intValue("AD_Table_ID");
            int sourceId = record.intValue("Record_ID");
            if (tableId <= 0 || sourceId <= 0) return null;
            String source = tableName(record.transactionName(), tableId);
            return source != null && HEADERS.containsKey(source) ? sourceDocument(source, sourceId, record) : null;
        }
        return null;
    }

    /** A stored source document, classified from its own committed-or-current row. */
    private NativeOperation sourceDocument(String header, int id, NativeRecord record) throws Exception {
        if (SALES_SIDE_ONLY.contains(header) && !salesSide(record.transactionName(), header, id)) {
            return null;
        }
        return new NativeOperation(HEADERS.get(header), header, id, record);
    }

    private String tableName(String trx, int adTableId) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        try (PreparedStatement s = db.prepareStatement(
                "SELECT tablename FROM adempiere.ad_table WHERE ad_table_id = ?")) {
            s.setInt(1, adTableId);
            try (ResultSet r = s.executeQuery()) {
                return r.next() ? r.getString(1) : null;
            }
        }
    }

    private boolean salesSide(String trx, String header, int id) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        // Table names come only from the closed map above, never from input.
        String relation = header.toLowerCase();
        try (PreparedStatement s = db.prepareStatement(
                "SELECT issotrx FROM adempiere." + relation + " WHERE " + relation + "_id = ?")) {
            s.setInt(1, id);
            try (ResultSet r = s.executeQuery()) {
                return r.next() && "Y".equals(r.getString(1));
            }
        }
    }
}
