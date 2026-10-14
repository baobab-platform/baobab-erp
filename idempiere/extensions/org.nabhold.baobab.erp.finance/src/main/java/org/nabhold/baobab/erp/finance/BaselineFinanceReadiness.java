package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Set;

/**
 * Platform-owned {@link NativeFinanceReadiness} (ADR-ERP-008, ADR-ERP-022),
 * read on the SAME native transaction. Ready means all of:
 * <ul>
 *   <li>the placement's AD_Client is active and has an active accounting schema;</li>
 *   <li>the Finance-approved baseline in force today for the placement's legal
 *       entity exists and is not withdrawn (no fallback to an older version);</li>
 *   <li>for a ledger line, its accounting period is open for the source
 *       document's base type.</li>
 * </ul>
 * CP authority never substitutes for any of these.
 */
final class BaselineFinanceReadiness implements NativeFinanceReadiness {
    private static final Set<String> DOCUMENT_TYPED = Set.of(
            "GL_Journal", "C_Invoice", "C_Payment", "C_AllocationHdr", "M_InOut", "C_Order",
            "C_BankStatement", "C_Cash");

    private final NativeConnections connections;

    BaselineFinanceReadiness(NativeConnections connections) {
        this.connections = connections;
    }

    @Override
    public FinanceBaseline currentBaseline(NativeOperation operation, NativePlacement placement) {
        if (operation == null || placement == null
                || placement.adClientId() != operation.record().adClientId()) {
            return null;
        }
        try {
            Connection db = NativeConnections.transactional(connections, operation.record().transactionName());
            if (!exists(db, "SELECT 1 FROM adempiere.ad_client WHERE ad_client_id = ? AND isactive = 'Y'",
                    placement.adClientId())
                    || !exists(db, "SELECT 1 FROM adempiere.c_acctschema WHERE ad_client_id = ? AND isactive = 'Y'",
                    placement.adClientId())) {
                return null;
            }
            Integer version = null;
            try (PreparedStatement s = db.prepareStatement("""
                    SELECT b.version,
                           EXISTS (SELECT 1 FROM baobab.financial_configuration_baseline_withdrawal w
                                    WHERE w.legal_entity_id = b.legal_entity_id AND w.version = b.version)
                      FROM baobab.financial_configuration_baseline b
                     WHERE b.legal_entity_id = ? AND b.effective_from <= current_date
                     ORDER BY b.effective_from DESC, b.version DESC
                     LIMIT 1""")) {
                s.setString(1, placement.legalEntityId());
                try (ResultSet r = s.executeQuery()) {
                    if (r.next() && !r.getBoolean(2)) version = r.getInt(1);
                }
            }
            if (version == null) return null;
            if ("Fact_Acct".equals(operation.record().table()) && !periodOpen(db, operation)) {
                return null;
            }
            return new FinanceBaseline(placement.legalEntityId(), version);
        } catch (Exception unavailable) {
            return null;
        }
    }

    private boolean periodOpen(Connection db, NativeOperation operation) throws Exception {
        int period = operation.record().intValue("C_Period_ID");
        String source = operation.sourceTable();
        if (period <= 0 || !DOCUMENT_TYPED.contains(source)) return false;
        String relation = source.toLowerCase(); // closed set above
        String baseType = null;
        try (PreparedStatement s = db.prepareStatement("SELECT dt.docbasetype FROM adempiere." + relation + " h"
                + " JOIN adempiere.c_doctype dt ON dt.c_doctype_id = h.c_doctype_id WHERE h." + relation + "_id = ?")) {
            s.setInt(1, operation.sourceRecordId());
            try (ResultSet r = s.executeQuery()) {
                if (r.next()) baseType = r.getString(1);
            }
        }
        if (baseType == null) return false;
        try (PreparedStatement s = db.prepareStatement("""
                SELECT 1 FROM adempiere.c_periodcontrol pc
                  JOIN adempiere.c_period p ON p.c_period_id = pc.c_period_id
                 WHERE pc.c_period_id = ? AND p.ad_client_id = ?
                   AND pc.docbasetype = ? AND pc.periodstatus = 'O'""")) {
            // Another client's open period never makes this client ready.
            s.setInt(1, period);
            s.setInt(2, operation.record().adClientId());
            s.setString(3, baseType);
            try (ResultSet r = s.executeQuery()) {
                return r.next();
            }
        }
    }

    private static boolean exists(Connection db, String sql, int id) throws Exception {
        try (PreparedStatement s = db.prepareStatement(sql)) {
            s.setInt(1, id);
            try (ResultSet r = s.executeQuery()) {
                return r.next();
            }
        }
    }
}
