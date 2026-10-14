package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.List;
import java.util.Map;

/**
 * ERP's table-to-operation policy (ADR-ERP-022): classifies a protected native
 * write into exactly one Shared erp/v2 operation class and its source document,
 * or returns null so the write is DENIED in a protected runtime.
 *
 * Purchase-side documents (vendor invoices, purchase orders, material
 * receipts), outbound payments, bank statements, cash journals and accounting
 * configuration (schema, chart, tax, bank accounts) have no catalogued class
 * yet and therefore stay denied. Permission to record money received is never
 * permission to disburse it: a payment is governed only as a receipt, and an
 * allocation only between sales invoices and receipts (owner decision,
 * P0-04B-05).
 *
 * Costing rows are not operations of their own: an M_CostDetail is classified
 * as the catalogued root document that deterministically caused it, in the
 * same transaction (only a sales shipment line today). Every other costing
 * origin stays denied until it is catalogued.
 */
final class NativeOperationResolver {
    /** Header tables: the governed source documents and their class. */
    private static final Map<String, String> HEADERS = Map.of(
            "GL_Journal", NativeOperation.GL_JOURNAL,
            "C_Invoice", NativeOperation.CUSTOMER_INVOICE,
            "C_Payment", NativeOperation.PAYMENT,
            "C_AllocationHdr", NativeOperation.ALLOCATION,
            "M_InOut", NativeOperation.SHIPMENT,
            "C_Order", NativeOperation.SALES_ORDER);
    /** Line tables and the header they belong to. */
    private static final Map<String, String> LINES = Map.of(
            "GL_JournalLine", "GL_Journal",
            "C_InvoiceLine", "C_Invoice",
            "C_AllocationLine", "C_AllocationHdr",
            "M_InOutLine", "M_InOut",
            "C_OrderLine", "C_Order");
    /** The governed direction of each directional header: sales side, or money received. */
    private static final Map<String, String> DIRECTION = Map.of(
            "C_Invoice", "IsSOTrx", "M_InOut", "IsSOTrx", "C_Order", "IsSOTrx", "C_Payment", "IsReceipt");
    /** Every source a cost detail can reference; exactly one may be set (M_InOutLine_ID). */
    private static final List<String> COST_SOURCES = List.of(
            "M_InOutLine_ID", "C_InvoiceLine_ID", "C_OrderLine_ID", "M_InventoryLine_ID",
            "M_MovementLine_ID", "M_ProductionLine_ID", "M_MatchInv_ID", "M_MatchPO_ID",
            "C_ProjectIssue_ID", "C_LandedCostAllocation_ID", "A_Asset_ID");

    private final NativeConnections connections;

    NativeOperationResolver(NativeConnections connections) {
        this.connections = connections;
    }

    NativeOperation classify(NativeRecord record) throws Exception {
        String table = record.table();
        if (HEADERS.containsKey(table)) {
            String direction = DIRECTION.get(table);
            // The PO's own value: a document being saved with the wrong direction is denied.
            if (direction != null && !Boolean.TRUE.equals(record.flag(direction))) {
                return null;
            }
            if ("C_AllocationHdr".equals(table) && record.recordId() > 0
                    && !allocationGoverned(record.transactionName(), record.recordId())) {
                return null;
            }
            return new NativeOperation(HEADERS.get(table), table, Math.max(record.recordId(), 0), record);
        }
        String header = LINES.get(table);
        if (header != null) {
            int headerId = record.intValue(header + "_ID");
            if (headerId <= 0) return null;
            if ("C_AllocationLine".equals(table) && !allocationLineGoverned(record)) return null;
            return sourceDocument(header, headerId, record);
        }
        if ("Fact_Acct".equals(table)) {
            int tableId = record.intValue("AD_Table_ID");
            int sourceId = record.intValue("Record_ID");
            if (tableId <= 0 || sourceId <= 0) return null;
            String source = tableName(record.transactionName(), tableId);
            return source != null && HEADERS.containsKey(source) ? sourceDocument(source, sourceId, record) : null;
        }
        if ("M_CostDetail".equals(table)) {
            return costDetailRoot(record);
        }
        return null;
    }

    /**
     * A cost detail inherits only from the sales shipment that caused it: its
     * single source reference is an M_InOutLine of a sales M_InOut in the same
     * client, and its org is that shipment's org or 0 (client-level costing).
     */
    private NativeOperation costDetailRoot(NativeRecord record) throws Exception {
        for (String source : COST_SOURCES) {
            if (!"M_InOutLine_ID".equals(source) && record.intValue(source) > 0) return null;
        }
        int line = record.intValue("M_InOutLine_ID");
        if (line <= 0 || !Boolean.TRUE.equals(record.flag("IsSOTrx"))) return null;
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        try (PreparedStatement s = db.prepareStatement("""
                SELECT io.m_inout_id, io.ad_client_id, io.ad_org_id, io.issotrx
                  FROM adempiere.m_inoutline l JOIN adempiere.m_inout io ON io.m_inout_id = l.m_inout_id
                 WHERE l.m_inoutline_id = ?""")) {
            s.setInt(1, line);
            try (ResultSet r = s.executeQuery()) {
                if (!r.next() || !"Y".equals(r.getString(4)) || r.getInt(2) != record.adClientId()
                        || (record.adOrgId() != 0 && r.getInt(3) != record.adOrgId())) {
                    return null;
                }
                return new NativeOperation(NativeOperation.SHIPMENT, "M_InOut", r.getInt(1), record);
            }
        }
    }

    /** An allocation line may only join a sales invoice and a received payment. */
    private boolean allocationLineGoverned(NativeRecord record) throws Exception {
        int invoice = record.intValue("C_Invoice_ID");
        int payment = record.intValue("C_Payment_ID");
        return (invoice <= 0 || directionHolds(record.transactionName(), "C_Invoice", invoice))
                && (payment <= 0 || directionHolds(record.transactionName(), "C_Payment", payment));
    }

    /** Every stored line of the allocation joins only sales invoices and receipts. */
    private boolean allocationGoverned(String trx, int allocationId) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        try (PreparedStatement s = db.prepareStatement("""
                SELECT NOT EXISTS (
                  SELECT 1 FROM adempiere.c_allocationline al
                    LEFT JOIN adempiere.c_invoice i ON i.c_invoice_id = al.c_invoice_id
                    LEFT JOIN adempiere.c_payment p ON p.c_payment_id = al.c_payment_id
                   WHERE al.c_allocationhdr_id = ?
                     AND ((al.c_invoice_id IS NOT NULL AND al.c_invoice_id > 0 AND i.issotrx IS DISTINCT FROM 'Y')
                       OR (al.c_payment_id IS NOT NULL AND al.c_payment_id > 0 AND p.isreceipt IS DISTINCT FROM 'Y')))""")) {
            s.setInt(1, allocationId);
            try (ResultSet r = s.executeQuery()) {
                return r.next() && r.getBoolean(1);
            }
        }
    }

    /** A stored source document, classified from its own committed-or-current row. */
    private NativeOperation sourceDocument(String header, int id, NativeRecord record) throws Exception {
        if (DIRECTION.containsKey(header) && !directionHolds(record.transactionName(), header, id)) {
            return null;
        }
        if ("C_AllocationHdr".equals(header) && !allocationGoverned(record.transactionName(), id)) {
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

    /** The transaction-visible stored row, never a caller value, holds the governed direction. */
    private boolean directionHolds(String trx, String header, int id) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        // Table and column names come only from the closed maps above, never from input.
        String relation = header.toLowerCase();
        try (PreparedStatement s = db.prepareStatement("SELECT " + DIRECTION.get(header).toLowerCase()
                + " FROM adempiere." + relation + " WHERE " + relation + "_id = ?")) {
            s.setInt(1, id);
            try (ResultSet r = s.executeQuery()) {
                return r.next() && "Y".equals(r.getString(1));
            }
        }
    }
}
