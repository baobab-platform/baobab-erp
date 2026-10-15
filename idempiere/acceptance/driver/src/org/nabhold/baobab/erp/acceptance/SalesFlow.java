package org.nabhold.baobab.erp.acceptance;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.util.Properties;

import org.compiere.model.MAllocationHdr;
import org.compiere.model.MAllocationLine;
import org.compiere.model.MBPartner;
import org.compiere.model.MInOut;
import org.compiere.model.MInOutLine;
import org.compiere.model.MInvoice;
import org.compiere.model.MInvoiceLine;
import org.compiere.model.MOrder;
import org.compiere.model.MOrderLine;
import org.compiere.model.MPayment;
import org.compiere.model.MTable;
import org.compiere.model.PO;
import org.compiere.process.DocAction;
import org.compiere.process.DocumentEngine;
import org.compiere.util.DB;
import org.compiere.util.Trx;

/**
 * Gate D (CI only) sales-side documents on GardenWorld: sales order, shipment,
 * customer invoice, receipt (or, to prove denial, an outbound payment) and a
 * manual allocation, each created, completed and posted through the REAL
 * iDempiere engine and the installed Baobab finance veto. Seed ids are found
 * by query, never hard-coded. Holds no authority.
 */
final class SalesFlow {
    private static final int CLIENT = 11;

    private SalesFlow() {}

    /** action=doc kind=order|shipment|invoice|payment|allocation [complete post rollbackAfterPost ...]. */
    static Properties document(Properties in, Properties ctx) {
        String kind = in.getProperty("kind");
        return process(in, ctx, trxName -> switch (kind) {
            case "order" -> order(in, ctx, trxName);
            case "shipment" -> shipment(in, ctx, trxName);
            case "invoice" -> invoice(in, ctx, trxName);
            case "payment" -> payment(in, ctx, trxName);
            case "allocation" -> allocation(in, ctx, trxName);
            default -> throw new IllegalArgumentException("unknown kind " + kind);
        });
    }

    /** Builds one native document inside the driver's transaction. */
    interface Builder {
        PO build(String trxName) throws Exception;
    }

    /**
     * Create (via builder), complete, commit and post one document as a user
     * does, or inject a failure after posting and before commit; shared by the
     * sales and purchase flows so both prove the same completion semantics.
     */
    static Properties process(Properties in, Properties ctx, Builder builder) {
        Properties out = new Properties();
        boolean complete = Boolean.parseBoolean(in.getProperty("complete", "true"));
        boolean post = Boolean.parseBoolean(in.getProperty("post", "true"));
        boolean rollbackAfterPost = Boolean.parseBoolean(in.getProperty("rollbackAfterPost", "false"));
        String trxName = Trx.createTrxName("BaobabGateD");
        Trx trx = Trx.get(trxName, true);
        try {
            PO doc = builder.build(trxName);
            out.setProperty("id", String.valueOf(doc.get_ID()));
            out.setProperty("table", doc.get_TableName());
            out.setProperty("table_id", String.valueOf(doc.get_Table_ID()));
            if (complete) {
                // As a user does: request Complete (a new order defaults to Prepare only).
                doc.set_ValueOfColumn("DocAction", DocAction.ACTION_Complete);
                DocAction action = (DocAction) doc;
                boolean ok = action.processIt(DocAction.ACTION_Complete);
                out.setProperty("complete_ok", String.valueOf(ok));
                if (!ok) out.setProperty("complete_msg", String.valueOf(action.getProcessMsg()));
                doc.saveEx();
            }
            if (rollbackAfterPost) {
                // Injected failure AFTER ledger and cost rows exist in this transaction, BEFORE commit.
                String err = DocumentEngine.postImmediate(ctx, CLIENT, doc.get_Table_ID(), doc.get_ID(), true, trxName);
                out.setProperty("post_error", String.valueOf(err));
                out.setProperty("facts_before_rollback", String.valueOf(DB.getSQLValueEx(trxName,
                        "SELECT COUNT(*) FROM Fact_Acct WHERE AD_Table_ID=? AND Record_ID=?", doc.get_Table_ID(), doc.get_ID())));
                out.setProperty("costs_before_rollback", String.valueOf(DB.getSQLValueEx(trxName,
                        "SELECT COUNT(*) FROM M_CostDetail cd JOIN M_InOutLine l ON l.M_InOutLine_ID=cd.M_InOutLine_ID "
                                + "WHERE l.M_InOut_ID=?", doc.get_ID())));
                out.setProperty("matches_before_rollback", String.valueOf(DB.getSQLValueEx(trxName,
                        "SELECT (SELECT COUNT(*) FROM M_MatchPO mp JOIN M_InOutLine l ON l.M_InOutLine_ID=mp.M_InOutLine_ID "
                                + "WHERE l.M_InOut_ID=?) + (SELECT COUNT(*) FROM M_MatchInv mi JOIN C_InvoiceLine il "
                                + "ON il.C_InvoiceLine_ID=mi.C_InvoiceLine_ID WHERE il.C_Invoice_ID=?)", doc.get_ID(), doc.get_ID())));
                trx.rollback();
                out.setProperty("committed", "false");
            } else {
                out.setProperty("committed", String.valueOf(trx.commit(true)));
                if (complete && post && "true".equals(out.getProperty("complete_ok"))) {
                    out.setProperty("post_error", String.valueOf(
                            DocumentEngine.postImmediate(ctx, CLIENT, doc.get_Table_ID(), doc.get_ID(), false, null)));
                }
            }
        } catch (Exception failed) {
            trx.rollback();
            out.setProperty("error", String.valueOf(failed.getMessage()));
        } finally {
            trx.close();
        }
        return out;
    }

    /** Complete (and post) an existing document of any governed table. */
    static Properties completeExisting(Properties in, Properties ctx) {
        Properties out = new Properties();
        String table = in.getProperty("table");
        int id = Integer.parseInt(in.getProperty("id"));
        String trxName = Trx.createTrxName("BaobabGateD");
        Trx trx = Trx.get(trxName, true);
        try {
            PO doc = MTable.get(ctx, table).getPO(id, trxName);
            doc.set_ValueOfColumn("DocAction", DocAction.ACTION_Complete);
            DocAction action = (DocAction) doc;
            boolean ok = action.processIt(DocAction.ACTION_Complete);
            out.setProperty("complete_ok", String.valueOf(ok));
            if (!ok) out.setProperty("complete_msg", String.valueOf(action.getProcessMsg()));
            doc.saveEx();
            out.setProperty("committed", String.valueOf(trx.commit(true)));
            if (ok) {
                out.setProperty("post_error", String.valueOf(
                        DocumentEngine.postImmediate(ctx, CLIENT, doc.get_Table_ID(), id, false, null)));
            }
        } catch (Exception failed) {
            trx.rollback();
            out.setProperty("error", String.valueOf(failed.getMessage()));
        } finally {
            trx.close();
        }
        return out;
    }

    /** Post an existing document again in iDempiere's own posting transaction (accounting-processor path). */
    static Properties repost(Properties in, Properties ctx) {
        Properties out = new Properties();
        int tableId = MTable.getTable_ID(in.getProperty("table"));
        int id = Integer.parseInt(in.getProperty("id"));
        boolean force = Boolean.parseBoolean(in.getProperty("force", "false"));
        out.setProperty("post_error", String.valueOf(DocumentEngine.postImmediate(ctx, CLIENT, tableId, id, force, null)));
        return out;
    }

    private static int org(Properties in) {
        return Integer.parseInt(in.getProperty("org", "11"));
    }

    private static int customer() {
        return DB.getSQLValueEx(null, "SELECT MIN(C_BPartner_ID) FROM C_BPartner WHERE AD_Client_ID=? AND Name='Joe Block'"
                + " AND IsCustomer='Y' AND IsActive='Y'", CLIENT);
    }

    private static MOrder order(Properties in, Properties ctx, String trx) {
        int org = org(in);
        int warehouse = DB.getSQLValueEx(null, "SELECT MIN(M_Warehouse_ID) FROM M_Warehouse WHERE AD_Client_ID=? AND AD_Org_ID=?"
                + " AND IsActive='Y'", CLIENT, org);
        int priceList = DB.getSQLValueEx(null, "SELECT MIN(M_PriceList_ID) FROM M_PriceList WHERE AD_Client_ID=?"
                + " AND IsSOPriceList='Y' AND IsDefault='Y' AND IsActive='Y'", CLIENT);
        // A stocked item with a sales price and stock on hand in this org's warehouse.
        int product = DB.getSQLValueEx(null, """
                SELECT MIN(p.M_Product_ID) FROM M_Product p
                 WHERE p.AD_Client_ID=? AND p.IsStocked='Y' AND p.ProductType='I' AND p.IsActive='Y' AND p.IsSold='Y'
                   AND EXISTS (SELECT 1 FROM M_ProductPrice pp JOIN M_PriceList_Version v
                                 ON v.M_PriceList_Version_ID=pp.M_PriceList_Version_ID
                                WHERE pp.M_Product_ID=p.M_Product_ID AND v.M_PriceList_ID=? AND pp.PriceStd > 0)
                   AND EXISTS (SELECT 1 FROM M_Cost c JOIN M_CostElement ce ON ce.M_CostElement_ID=c.M_CostElement_ID
                                WHERE c.M_Product_ID=p.M_Product_ID AND ce.CostingMethod='S' AND c.CurrentCostPrice > 0)
                   AND (SELECT COALESCE(SUM(s.QtyOnHand),0) FROM M_StorageOnHand s JOIN M_Locator l
                          ON l.M_Locator_ID=s.M_Locator_ID WHERE s.M_Product_ID=p.M_Product_ID AND l.M_Warehouse_ID=?) >= 10""",
                CLIENT, priceList, warehouse);
        MOrder o = new MOrder(ctx, 0, trx);
        o.setAD_Org_ID(org);
        o.setIsSOTrx(true);
        o.setC_DocTypeTarget_ID(MOrder.DocSubTypeSO_Standard);
        o.setBPartner(MBPartner.get(ctx, customer()));
        o.setM_Warehouse_ID(warehouse);
        o.setM_PriceList_ID(priceList);
        o.setDescription("Baobab Gate D synthetic sales order (CI only)");
        o.saveEx();
        MOrderLine l = new MOrderLine(o);
        l.setM_Product_ID(product, true);
        l.setQty(new BigDecimal(in.getProperty("qty", "1")));
        l.setPrice();
        l.saveEx();
        return o;
    }

    private static MInOut shipment(Properties in, Properties ctx, String trx) {
        MOrder o = new MOrder(ctx, Integer.parseInt(in.getProperty("order_id")), trx);
        MInOut io = new MInOut(o, 0, new Timestamp(System.currentTimeMillis()));
        io.saveEx();
        for (MOrderLine ol : o.getLines()) {
            int locator = DB.getSQLValueEx(null, """
                    SELECT MIN(s.M_Locator_ID) FROM M_StorageOnHand s JOIN M_Locator l ON l.M_Locator_ID=s.M_Locator_ID
                     WHERE s.M_Product_ID=? AND l.M_Warehouse_ID=? AND s.QtyOnHand >= ?""",
                    ol.getM_Product_ID(), o.getM_Warehouse_ID(), ol.getQtyOrdered());
            MInOutLine iol = new MInOutLine(io);
            iol.setOrderLine(ol, locator, ol.getQtyOrdered());
            iol.setQty(ol.getQtyOrdered());
            iol.saveEx();
        }
        return io;
    }

    private static MInvoice invoice(Properties in, Properties ctx, String trx) {
        MOrder o = new MOrder(ctx, Integer.parseInt(in.getProperty("order_id")), trx);
        MInvoice inv = new MInvoice(o, 0, new Timestamp(System.currentTimeMillis()));
        inv.saveEx();
        for (MOrderLine ol : o.getLines()) {
            MInvoiceLine il = new MInvoiceLine(inv);
            il.setOrderLine(ol);
            il.setQty(ol.getQtyOrdered());
            il.saveEx();
        }
        return inv;
    }

    private static MPayment payment(Properties in, Properties ctx, String trx) {
        boolean receipt = !"out".equals(in.getProperty("direction", "in"));
        int org = org(in);
        int bankAccount = DB.getSQLValueEx(null, "SELECT MIN(C_BankAccount_ID) FROM C_BankAccount WHERE AD_Client_ID=?"
                + " AND IsActive='Y' AND AD_Org_ID IN (0, ?)", CLIENT, org);
        MPayment p = new MPayment(ctx, 0, trx);
        p.setAD_Org_ID(org);
        p.setC_BankAccount_ID(bankAccount);
        p.setIsReceipt(receipt);
        p.setC_DocType_ID(receipt);
        p.setTenderType(MPayment.TENDERTYPE_Check);
        p.setC_BPartner_ID(customer());
        int invoice = Integer.parseInt(in.getProperty("invoice_id", "0"));
        if (invoice > 0) {
            MInvoice inv = new MInvoice(ctx, invoice, trx);
            p.setC_Invoice_ID(invoice);
            p.setC_Currency_ID(inv.getC_Currency_ID());
            p.setPayAmt(inv.getGrandTotal());
        } else {
            p.setC_Currency_ID(DB.getSQLValueEx(null, "SELECT C_Currency_ID FROM C_AcctSchema WHERE C_AcctSchema_ID="
                    + "(SELECT C_AcctSchema1_ID FROM AD_ClientInfo WHERE AD_Client_ID=?)", CLIENT));
            p.setPayAmt(new BigDecimal(in.getProperty("amount", "10.00")));
        }
        Timestamp now = new Timestamp(System.currentTimeMillis());
        p.setDateTrx(now);
        p.setDateAcct(now);
        p.setDescription("Baobab Gate D synthetic payment (CI only)");
        p.saveEx();
        return p;
    }

    /** A manual allocation of an unallocated payment against an open invoice. */
    private static MAllocationHdr allocation(Properties in, Properties ctx, String trx) {
        MInvoice inv = new MInvoice(ctx, Integer.parseInt(in.getProperty("invoice_id")), trx);
        int payment = Integer.parseInt(in.getProperty("payment_id"));
        BigDecimal amount = new BigDecimal(in.getProperty("amount", inv.getGrandTotal().toPlainString()));
        Timestamp now = new Timestamp(System.currentTimeMillis());
        MAllocationHdr a = new MAllocationHdr(ctx, true, now, inv.getC_Currency_ID(),
                "Baobab Gate D synthetic allocation (CI only)", trx);
        a.setAD_Org_ID(inv.getAD_Org_ID());
        a.saveEx();
        MAllocationLine l = new MAllocationLine(a, amount, BigDecimal.ZERO, BigDecimal.ZERO,
                inv.getGrandTotal().subtract(amount));
        l.setDocInfo(inv.getC_BPartner_ID(), 0, inv.getC_Invoice_ID());
        l.setPaymentInfo(payment, 0);
        l.saveEx();
        return a;
    }
}
