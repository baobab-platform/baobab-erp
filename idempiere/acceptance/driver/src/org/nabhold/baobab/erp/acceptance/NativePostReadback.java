package org.nabhold.baobab.erp.acceptance;

import java.util.Properties;
import java.util.Set;

import org.compiere.process.DocumentEngine;
import org.compiere.util.DB;

/**
 * Acceptance-only bridge. Do not run the posting processor twice after iDempiere
 * has completed and posted a document: Doc.post() starts by deleting its prior
 * Fact_Acct rows, which is forbidden for historically placed clients (N0010).
 *
 * This DOES NOT post or change a document. It observes committed iDempiere
 * status on an independent DB read and invokes the genuine iDempiere posting
 * engine only when the source is not yet posted. The harness separately proves
 * that committed finance facts exist, balance, and have CP attribution.
 * Never infer posted status from a replay request or an in-memory model.
 */
final class NativePostReadback {
    private static final Set<String> TABLES = Set.of(
            "GL_Journal", "C_Order", "M_InOut", "C_Invoice", "C_Payment", "C_AllocationHdr");

    private NativePostReadback() {}

    static String postIfNeeded(Properties ctx, int client, String table, int tableId, int recordId) {
        if (!TABLES.contains(table) || recordId <= 0 || client <= 0) {
            throw new IllegalArgumentException("unsupported native posting source");
        }
        int alreadyPosted = DB.getSQLValueEx(null,
                "SELECT count(*) FROM " + table
                + " WHERE " + table + "_ID=? AND AD_Client_ID=?"
                + " AND DocStatus IN ('CO','CL') AND Posted='Y'",
                recordId, client);
        if (alreadyPosted == 1) {
            // The native document already has a completed posting. Do not call
            // Doc.post() again: it may delete a committed journal, invoice,
            // shipment or payment ledger. Independent harness readback remains
            // mandatory: Posted='Y' alone does not prove accounting balances.
            return null;
        }
        if (alreadyPosted != 0) {
            throw new IllegalStateException("ambiguous native posting state");
        }
        return DocumentEngine.postImmediate(ctx, client, tableId, recordId, false, null);
    }
}
