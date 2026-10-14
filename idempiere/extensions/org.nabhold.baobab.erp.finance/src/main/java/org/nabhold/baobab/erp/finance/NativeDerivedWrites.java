package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/**
 * Transaction-bound costing consequences of an already-authorised root ERP
 * operation (ADR-ERP-022 amendment, P0-04B-05). A cost row never earns its own
 * CP decision: it may only inherit, in the SAME native transaction, the current
 * attribution of the catalogued root document that deterministically caused it.
 * The database refuses the record without that attribution, and its COMMIT
 * fences refuse any M_CostDetail/M_Cost write without a matching record.
 */
final class NativeDerivedWrites {
    private static final String APPEND = """
        INSERT INTO baobab_native.derived_write_attribution
        (root_table, root_record_id, decision_id, derived_table, ad_client_id, ad_org_id,
         m_product_id, c_acctschema_id, m_costelement_id)
        SELECT ?, ?, a.decision_id, ?, ?, ?, ?, ?, ?
          FROM baobab_native.finance_authority_attribution a
         WHERE a.txid = txid_current() AND a.ad_client_id = ? AND a.decision_id IS NOT NULL
           AND lower(a.source_table) = lower(?) AND a.source_record_id = ?
           AND a.authority_expires_at > clock_timestamp()
         ORDER BY a.received_at DESC LIMIT 1
        """;
    private static final String COST_COVERED = """
        SELECT EXISTS (
          SELECT 1 FROM baobab_native.derived_write_attribution d
           WHERE d.txid = txid_current() AND d.ad_client_id = ? AND d.m_product_id = ?
             AND d.c_acctschema_id = ? AND (d.ad_org_id = ? OR ? = 0)
             AND baobab_native.has_current_attribution(d.ad_client_id, d.root_table, d.root_record_id))
        """;

    private final NativeConnections connections;

    NativeDerivedWrites(NativeConnections connections) {
        this.connections = connections;
    }

    /** Records that this cost detail is a consequence of its authorised root, or throws. */
    void appendCostDetail(NativeOperation root) throws Exception {
        NativeRecord record = root.record();
        int product = record.intValue("M_Product_ID");
        int schema = record.intValue("C_AcctSchema_ID");
        if (product <= 0 || schema <= 0 || root.sourceRecordId() <= 0) {
            throw new IllegalArgumentException("cost detail has no product, schema or root");
        }
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        try (PreparedStatement s = db.prepareStatement(APPEND)) {
            s.setString(1, root.sourceTable());
            s.setInt(2, root.sourceRecordId());
            s.setString(3, record.table());
            s.setInt(4, record.adClientId());
            s.setInt(5, record.adOrgId());
            s.setInt(6, product);
            s.setInt(7, schema);
            s.setInt(8, Math.max(record.intValue("M_CostElement_ID"), 0));
            s.setInt(9, record.adClientId());
            s.setString(10, root.sourceTable());
            s.setInt(11, root.sourceRecordId());
            if (s.executeUpdate() != 1) {
                throw new SQLException("cost detail has no current root attribution in this transaction");
            }
        }
    }

    /** An M_Cost write is covered only by a cost detail already derived in this transaction. */
    boolean costCovered(NativeRecord record) throws Exception {
        int product = record.intValue("M_Product_ID");
        int schema = record.intValue("C_AcctSchema_ID");
        if (product <= 0 || schema <= 0 || record.adClientId() <= 0 || record.adOrgId() < 0) return false;
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        try (PreparedStatement s = db.prepareStatement(COST_COVERED)) {
            s.setInt(1, record.adClientId());
            s.setInt(2, product);
            s.setInt(3, schema);
            s.setInt(4, record.adOrgId());
            s.setInt(5, record.adOrgId());
            try (ResultSet r = s.executeQuery()) {
                return r.next() && r.getBoolean(1);
            }
        }
    }
}
