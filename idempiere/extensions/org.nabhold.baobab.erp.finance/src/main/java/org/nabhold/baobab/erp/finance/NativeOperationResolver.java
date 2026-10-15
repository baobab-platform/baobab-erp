package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * ERP's table-to-operation policy (ADR-ERP-022): classifies a protected native
 * write into exactly one Shared erp/v2 operation class and its source document,
 * or returns null so the write is DENIED in a protected runtime.
 *
 * A header being saved is classified from its own values (the PO's, never a
 * caller's). Every stored source document is classified by the database's
 * baobab_native.governed_class_of (N0006), the same rule the COMMIT fence
 * applies, so the JVM veto and the fence can never disagree on a class:
 * sales side, or purchase side (a purchase order, a vendor receipt (V+), an AP
 * invoice, an outbound payment that is neither online nor from a payment
 * selection, and an allocation joining only those). Vendor returns, AP credit
 * memos, mixed AP/AR allocations, payment selections, bank statements, cash
 * journals and accounting configuration have no class and stay denied.
 * Recording a vendor payment is never permission to disburse (ADR-SHARED-035).
 *
 * Matching rows and costing rows are not operations of their own: a match is
 * classified as its one deterministic root document; a cost detail as the
 * catalogued root that caused it in the same transaction (only a sales
 * shipment line today). Every other costing origin stays denied until it is
 * catalogued.
 */
final class NativeOperationResolver {
    /** Header tables: the governed source documents. */
    private static final Set<String> HEADERS = Set.of(
            "GL_Journal", "C_Invoice", "C_Payment", "C_AllocationHdr", "M_InOut", "C_Order");
    /** Line tables and the header they belong to. */
    private static final Map<String, String> LINES = Map.of(
            "GL_JournalLine", "GL_Journal",
            "C_InvoiceLine", "C_Invoice",
            "C_AllocationLine", "C_AllocationHdr",
            "M_InOutLine", "M_InOut",
            "C_OrderLine", "C_Order");
    /** Every source a cost detail can reference; exactly one may be set (M_InOutLine_ID). */
    private static final List<String> COST_SOURCES = List.of(
            "M_InOutLine_ID", "C_InvoiceLine_ID", "C_OrderLine_ID", "M_InventoryLine_ID",
            "M_MovementLine_ID", "M_ProductionLine_ID", "M_MatchInv_ID", "M_MatchPO_ID",
            "C_ProjectIssue_ID", "C_LandedCostAllocation_ID", "A_Asset_ID");
    private static final String STORED_CLASS = "SELECT baobab_native.governed_class_of(?, ?)";
    private static final String ROOT = "SELECT root_table, root_record FROM baobab_native.governed_root(?, ?)";
    private static final String LINE_SIDE = "SELECT baobab_native.allocation_line_side(?, ?)";

    private final NativeConnections connections;

    NativeOperationResolver(NativeConnections connections) {
        this.connections = connections;
    }

    NativeOperation classify(NativeRecord record) throws Exception {
        String table = record.table();
        if (HEADERS.contains(table)) {
            String operationClass = headerClass(record);
            return operationClass == null ? null
                    : new NativeOperation(operationClass, table, Math.max(record.recordId(), 0), record);
        }
        String header = LINES.get(table);
        if (header != null) {
            int headerId = record.intValue(header + "_ID");
            if (headerId <= 0) return null;
            if ("C_AllocationLine".equals(table)) return allocationLine(record, headerId);
            return sourceDocument(header, headerId, record);
        }
        if ("Fact_Acct".equals(table)) {
            int tableId = record.intValue("AD_Table_ID");
            int sourceId = record.intValue("Record_ID");
            if (tableId <= 0 || sourceId <= 0) return null;
            String source = tableName(record.transactionName(), tableId);
            if (source == null) return null;
            return root(source, sourceId, record);
        }
        if ("M_MatchPO".equals(table) || "M_MatchInv".equals(table)) {
            return matchRoot(record);
        }
        if ("M_CostDetail".equals(table)) {
            return costDetailRoot(record);
        }
        return null;
    }

    /**
     * True for an allocation header that is still an empty draft: iDempiere
     * saves an allocation header before any line, and only its lines decide
     * whether it is a sales or a payables allocation. Such a header has no
     * ledger effect; every line, completion and posting stays classified and
     * fenced at COMMIT by its lines' direction (N0006).
     */
    boolean emptyDraftAllocation(NativeRecord record) throws Exception {
        if (!"C_AllocationHdr".equals(record.table()) || record.action() == null
                || !record.action().startsWith("model:")) {
            return false;
        }
        Object status = record.value("DocStatus");
        if (!("DR".equals(status) || "IP".equals(status))) return false;
        if (record.recordId() <= 0) return true;
        return emptyAllocation(record.transactionName(), record.recordId(), 0);
    }

    /** The class of a header being saved, from its own values; a stored allocation by its lines. */
    private String headerClass(NativeRecord record) throws Exception {
        Boolean sales;
        switch (record.table()) {
            case "GL_Journal":
                return NativeOperation.GL_JOURNAL;
            case "C_Order":
                sales = record.flag("IsSOTrx");
                return sales == null ? null : sales ? NativeOperation.SALES_ORDER : NativeOperation.PURCHASE_ORDER;
            case "M_InOut":
                sales = record.flag("IsSOTrx");
                if (sales == null) return null;
                if (sales) return NativeOperation.SHIPMENT;
                return "V+".equals(record.value("MovementType")) ? NativeOperation.MATERIAL_RECEIPT : null;
            case "C_Invoice":
                sales = record.flag("IsSOTrx");
                if (sales == null) return null;
                if (sales) return NativeOperation.CUSTOMER_INVOICE;
                int docType = record.intValue("C_DocType_ID") > 0
                        ? record.intValue("C_DocType_ID") : record.intValue("C_DocTypeTarget_ID");
                return "API".equals(docBaseType(record.transactionName(), docType))
                        ? NativeOperation.VENDOR_INVOICE : null;
            case "C_Payment":
                Boolean receipt = record.flag("IsReceipt");
                if (receipt == null) return null;
                if (receipt) return NativeOperation.PAYMENT;
                // Recording only: an online outbound payment, or one a payment
                // selection generated, would be a native disbursement instruction.
                if (!Boolean.FALSE.equals(record.flag("IsOnline"))) return null;
                if (record.recordId() > 0 && inPaySelection(record.transactionName(), record.recordId())) return null;
                return NativeOperation.VENDOR_PAYMENT;
            case "C_AllocationHdr":
                return record.recordId() > 0
                        ? storedClass(record.transactionName(), "C_AllocationHdr", record.recordId()) : null;
            default:
                return null;
        }
    }

    /**
     * An allocation line joins only one side, and the allocation it joins is
     * either still empty or already on that same side: never AP/AR netting.
     */
    private NativeOperation allocationLine(NativeRecord record, int headerId) throws Exception {
        String side;
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        try (PreparedStatement s = db.prepareStatement(LINE_SIDE)) {
            int invoice = record.intValue("C_Invoice_ID");
            int payment = record.intValue("C_Payment_ID");
            s.setObject(1, invoice > 0 ? invoice : null, java.sql.Types.INTEGER);
            s.setObject(2, payment > 0 ? payment : null, java.sql.Types.INTEGER);
            try (ResultSet r = s.executeQuery()) {
                side = r.next() ? r.getString(1) : null;
            }
        }
        String lineClass = "SALES".equals(side) ? NativeOperation.ALLOCATION
                : "PAYABLES".equals(side) ? NativeOperation.PAYABLES_ALLOCATION : null;
        if (lineClass == null) return null;
        String stored = storedClass(record.transactionName(), "C_AllocationHdr", headerId);
        if (stored != null && !stored.equals(lineClass)) return null;
        if (stored == null && !emptyAllocation(record.transactionName(), headerId, record.recordId())) return null;
        return new NativeOperation(lineClass, "C_AllocationHdr", headerId, record);
    }

    /** True when the allocation has no stored line other than the one being saved. */
    private boolean emptyAllocation(String trx, int headerId, int lineId) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        try (PreparedStatement s = db.prepareStatement(
                "SELECT NOT EXISTS (SELECT 1 FROM adempiere.c_allocationline "
                        + "WHERE c_allocationhdr_id = ? AND c_allocationline_id <> ?)")) {
            s.setInt(1, headerId);
            s.setInt(2, Math.max(lineId, 0));
            try (ResultSet r = s.executeQuery()) {
                return r.next() && r.getBoolean(1);
            }
        }
    }

    /** A matching row is classified as its one deterministic root document (N0006 governed_root). */
    private NativeOperation matchRoot(NativeRecord record) throws Exception {
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        int receiptLine = record.intValue("M_InOutLine_ID");
        int invoiceLine = record.intValue("C_InvoiceLine_ID");
        String rootTable;
        String sql;
        int line;
        if ("M_MatchPO".equals(record.table()) && receiptLine > 0) {
            rootTable = "M_InOut";
            sql = "SELECT m_inout_id FROM adempiere.m_inoutline WHERE m_inoutline_id = ? AND ad_client_id = ?";
            line = receiptLine;
        } else if (invoiceLine > 0) {
            rootTable = "C_Invoice";
            sql = "SELECT c_invoice_id FROM adempiere.c_invoiceline WHERE c_invoiceline_id = ? AND ad_client_id = ?";
            line = invoiceLine;
        } else {
            return null;
        }
        int rootId;
        try (PreparedStatement s = db.prepareStatement(sql)) {
            s.setInt(1, line);
            s.setInt(2, record.adClientId());
            try (ResultSet r = s.executeQuery()) {
                if (!r.next()) return null;
                rootId = r.getInt(1);
            }
        }
        String operationClass = storedClass(record.transactionName(), rootTable, rootId);
        // Matching belongs to the purchase side only.
        if (!NativeOperation.MATERIAL_RECEIPT.equals(operationClass)
                && !NativeOperation.VENDOR_INVOICE.equals(operationClass)) {
            return null;
        }
        return new NativeOperation(operationClass, rootTable, rootId, record);
    }

    /** A ledger row's source document, or a matching row's root, with its stored class. */
    private NativeOperation root(String source, int sourceId, NativeRecord record) throws Exception {
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        String rootTable;
        int rootId;
        try (PreparedStatement s = db.prepareStatement(ROOT)) {
            s.setString(1, source);
            s.setInt(2, sourceId);
            try (ResultSet r = s.executeQuery()) {
                if (!r.next()) return null;
                rootTable = r.getString(1);
                rootId = r.getInt(2);
                if (r.wasNull()) return null;
            }
        }
        if (rootTable == null || !HEADERS.contains(rootTable)) return null;
        return sourceDocument(rootTable, rootId, record);
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

    /** A stored source document, classified from its own committed-or-current row. */
    private NativeOperation sourceDocument(String header, int id, NativeRecord record) throws Exception {
        String operationClass = storedClass(record.transactionName(), header, id);
        return operationClass == null ? null : new NativeOperation(operationClass, header, id, record);
    }

    /** The database's class for a stored source document (N0006), or null. */
    private String storedClass(String trx, String table, int id) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        try (PreparedStatement s = db.prepareStatement(STORED_CLASS)) {
            s.setString(1, table);
            s.setInt(2, id);
            try (ResultSet r = s.executeQuery()) {
                return r.next() ? r.getString(1) : null;
            }
        }
    }

    private String docBaseType(String trx, int docTypeId) throws Exception {
        if (docTypeId <= 0) return null;
        Connection db = NativeConnections.transactional(connections, trx);
        try (PreparedStatement s = db.prepareStatement(
                "SELECT docbasetype FROM adempiere.c_doctype WHERE c_doctype_id = ?")) {
            s.setInt(1, docTypeId);
            try (ResultSet r = s.executeQuery()) {
                return r.next() ? r.getString(1) : null;
            }
        }
    }

    /** Fail closed: an unreadable answer counts as part of a payment selection. */
    private boolean inPaySelection(String trx, int paymentId) throws Exception {
        Connection db = NativeConnections.transactional(connections, trx);
        try (PreparedStatement s = db.prepareStatement(
                "SELECT EXISTS (SELECT 1 FROM adempiere.c_payselectioncheck WHERE c_payment_id = ?)")) {
            s.setInt(1, paymentId);
            try (ResultSet r = s.executeQuery()) {
                return !r.next() || r.getBoolean(1);
            }
        }
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
}
