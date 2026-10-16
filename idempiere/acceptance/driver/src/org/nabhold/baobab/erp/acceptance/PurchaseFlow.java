package org.nabhold.baobab.erp.acceptance;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.util.Properties;

import org.compiere.model.MAllocationHdr;
import org.compiere.model.MAllocationLine;
import org.compiere.model.MBPartner;
import org.compiere.model.MBankAccount;
import org.compiere.model.MBankStatement;
import org.compiere.model.MCash;
import org.compiere.model.MInOut;
import org.compiere.model.MInOutLine;
import org.compiere.model.MInvoice;
import org.compiere.model.MInventory;
import org.compiere.model.MInvoiceLine;
import org.compiere.model.MOrder;
import org.compiere.model.MOrderLine;
import org.compiere.model.MPaySelection;
import org.compiere.model.MPayment;
import org.compiere.model.MWarehouse;
import org.compiere.model.PO;
import org.compiere.util.DB;

/**
 * Gate D (CI only) purchase-side documents on GardenWorld for ERP-A
 * (ADR-SHARED-037, ADR-ERP-022 §4.3): purchase order, vendor receipt, AP
 * invoice matched to the receipt, recorded vendor payment and a payables
 * allocation, each created, completed and posted through the REAL iDempiere
 * engine and the installed Baobab finance veto; plus the routes that must stay
 * denied (vendor return, AP credit memo, payment selection, online outbound
 * payment) and, for ERP-B (ADR-SHARED-038), the uncatalogued families denied by
 * name (bank statement, cash journal, physical inventory). Seed ids are found
 * by query, never hard-coded. Holds no authority.
 */
final class PurchaseFlow {
    private static final int CLIENT = 11;

    private PurchaseFlow() {}

    /** action=pdoc kind=po|receipt|vinvoice|vpayment|vallocation|vreturn|apcredit|payselection|bankstatement|cash|inventory. */
    static Properties document(Properties in, Properties ctx) {
        String kind = in.getProperty("kind");
        return SalesFlow.process(in, ctx, trxName -> switch (kind) {
            case "po" -> purchaseOrder(in, ctx, trxName);
            case "receipt" -> receipt(in, ctx, trxName, false);
            case "vreturn" -> receipt(in, ctx, trxName, true);
            case "vinvoice" -> vendorInvoice(in, ctx, trxName, "API");
            case "apcredit" -> vendorInvoice(in, ctx, trxName, "APC");
            case "vpayment" -> vendorPayment(in, ctx, trxName);
            case "vallocation" -> payablesAllocation(in, ctx, trxName);
            case "payselection" -> paySelection(in, ctx, trxName);
            case "bankstatement" -> bankStatement(in, ctx, trxName);
            case "cash" -> cashJournal(in, ctx, trxName);
            case "inventory" -> inventory(in, ctx, trxName);
            default -> throw new IllegalArgumentException("unknown kind " + kind);
        });
    }

    private static int org(Properties in) {
        return Integer.parseInt(in.getProperty("org", "11"));
    }

    private static int vendor() {
        // A GardenWorld vendor with a purchase-side business partner record.
        return DB.getSQLValueEx(null, "SELECT MIN(C_BPartner_ID) FROM C_BPartner WHERE AD_Client_ID=?"
                + " AND IsVendor='Y' AND IsActive='Y' AND Name LIKE 'Patio%'", CLIENT);
    }

    private static int docType(String baseType, boolean soTrx) {
        return DB.getSQLValueEx(null, "SELECT MIN(C_DocType_ID) FROM C_DocType WHERE AD_Client_ID=? AND DocBaseType=?"
                + " AND IsSOTrx=? AND IsActive='Y'", CLIENT, baseType, soTrx ? "Y" : "N");
    }

    private static MOrder purchaseOrder(Properties in, Properties ctx, String trx) {
        int org = org(in);
        int warehouse = DB.getSQLValueEx(null, "SELECT MIN(M_Warehouse_ID) FROM M_Warehouse WHERE AD_Client_ID=? AND AD_Org_ID=?"
                + " AND IsActive='Y'", CLIENT, org);
        int priceList = DB.getSQLValueEx(null, "SELECT MIN(M_PriceList_ID) FROM M_PriceList WHERE AD_Client_ID=?"
                + " AND IsSOPriceList='N' AND IsActive='Y'", CLIENT);
        // A stocked item with a purchase price on that list and a standard cost.
        int product = DB.getSQLValueEx(null, """
                SELECT MIN(p.M_Product_ID) FROM M_Product p
                 WHERE p.AD_Client_ID=? AND p.IsStocked='Y' AND p.ProductType='I' AND p.IsActive='Y' AND p.IsPurchased='Y'
                   AND EXISTS (SELECT 1 FROM M_ProductPrice pp JOIN M_PriceList_Version v
                                 ON v.M_PriceList_Version_ID=pp.M_PriceList_Version_ID
                                WHERE pp.M_Product_ID=p.M_Product_ID AND v.M_PriceList_ID=? AND pp.PriceStd > 0)
                   AND EXISTS (SELECT 1 FROM M_Cost c JOIN M_CostElement ce ON ce.M_CostElement_ID=c.M_CostElement_ID
                                WHERE c.M_Product_ID=p.M_Product_ID AND ce.CostingMethod='S' AND c.CurrentCostPrice > 0)""",
                CLIENT, priceList);
        MOrder o = new MOrder(ctx, 0, trx);
        o.setAD_Org_ID(org);
        o.setIsSOTrx(false);
        o.setC_DocTypeTarget_ID(docType("POO", false));
        o.setBPartner(MBPartner.get(ctx, vendor()));
        o.setM_Warehouse_ID(warehouse);
        o.setM_PriceList_ID(priceList);
        o.setDescription("Baobab Gate D synthetic purchase order (CI only)");
        o.saveEx();
        MOrderLine l = new MOrderLine(o);
        l.setM_Product_ID(product, true);
        l.setQty(new BigDecimal(in.getProperty("qty", "2")));
        l.setPrice();
        l.saveEx();
        return o;
    }

    /** A vendor receipt (MovementType V+) of every PO line, or with ret=true a vendor return (V-). */
    private static MInOut receipt(Properties in, Properties ctx, String trx, boolean vendorReturn) {
        MOrder o = new MOrder(ctx, Integer.parseInt(in.getProperty("order_id")), trx);
        // GardenWorld's purchase-order type names no receipt type: pass the vendor receipt (MMR) or,
        // for a return, the vendor-return type (MMS, purchase side) explicitly.
        int docType = vendorReturn ? docType("MMS", false) : docType("MMR", false);
        MInOut io = new MInOut(o, docType, new Timestamp(System.currentTimeMillis()));
        io.setDescription("Baobab Gate D synthetic " + (vendorReturn ? "vendor return" : "vendor receipt") + " (CI only)");
        io.saveEx();
        int locator = DB.getSQLValueEx(null, "SELECT MIN(M_Locator_ID) FROM M_Locator WHERE M_Warehouse_ID=? AND IsActive='Y'",
                o.getM_Warehouse_ID());
        for (MOrderLine ol : o.getLines()) {
            MInOutLine iol = new MInOutLine(io);
            iol.setOrderLine(ol, locator, ol.getQtyOrdered());
            iol.setQty(vendorReturn ? BigDecimal.ONE : ol.getQtyOrdered());
            iol.saveEx();
        }
        return io;
    }

    /** An AP invoice (or AP credit memo) for the PO, each line matched to its receipt line when given. */
    private static MInvoice vendorInvoice(Properties in, Properties ctx, String trx, String baseType) {
        MOrder o = new MOrder(ctx, Integer.parseInt(in.getProperty("order_id")), trx);
        int receipt = Integer.parseInt(in.getProperty("receipt_id", "0"));
        MInvoice inv = new MInvoice(o, docType(baseType, false), new Timestamp(System.currentTimeMillis()));
        inv.setDescription("Baobab Gate D synthetic " + baseType + " (CI only)");
        inv.saveEx();
        for (MOrderLine ol : o.getLines()) {
            MInvoiceLine il = new MInvoiceLine(inv);
            il.setOrderLine(ol);
            il.setQty("APC".equals(baseType) ? BigDecimal.ONE : ol.getQtyOrdered());
            if (receipt > 0) {
                int line = DB.getSQLValueEx(trx, "SELECT MIN(M_InOutLine_ID) FROM M_InOutLine WHERE M_InOut_ID=? AND C_OrderLine_ID=?",
                        receipt, ol.getC_OrderLine_ID());
                if (line > 0) il.setM_InOutLine_ID(line);
            }
            il.saveEx();
        }
        return inv;
    }

    /** An outbound payment RECORDED against the AP invoice; online=true makes it an online (denied) payment. */
    private static MPayment vendorPayment(Properties in, Properties ctx, String trx) {
        int org = org(in);
        int bankAccount = DB.getSQLValueEx(null, "SELECT MIN(C_BankAccount_ID) FROM C_BankAccount WHERE AD_Client_ID=?"
                + " AND IsActive='Y' AND AD_Org_ID IN (0, ?)", CLIENT, org);
        MPayment p = new MPayment(ctx, 0, trx);
        p.setAD_Org_ID(org);
        p.setC_BankAccount_ID(bankAccount);
        p.setIsReceipt(false);
        p.setC_DocType_ID(false);
        p.setTenderType(MPayment.TENDERTYPE_Check);
        p.setIsOnline(Boolean.parseBoolean(in.getProperty("online", "false")));
        p.setC_BPartner_ID(vendor());
        int invoice = Integer.parseInt(in.getProperty("invoice_id", "0"));
        if (invoice > 0) {
            MInvoice inv = new MInvoice(ctx, invoice, trx);
            p.setC_Currency_ID(inv.getC_Currency_ID());
            p.setPayAmt(inv.getGrandTotal());
            if (!Boolean.parseBoolean(in.getProperty("unallocated", "false"))) p.setC_Invoice_ID(invoice);
        } else {
            p.setC_Currency_ID(DB.getSQLValueEx(null, "SELECT C_Currency_ID FROM C_AcctSchema WHERE C_AcctSchema_ID="
                    + "(SELECT C_AcctSchema1_ID FROM AD_ClientInfo WHERE AD_Client_ID=?)", CLIENT));
            p.setPayAmt(new BigDecimal(in.getProperty("amount", "10.00")));
        }
        Timestamp now = new Timestamp(System.currentTimeMillis());
        p.setDateTrx(now);
        p.setDateAcct(now);
        p.setDescription("Baobab Gate D synthetic vendor payment record (CI only)");
        p.saveEx();
        return p;
    }

    /** A manual payables allocation of a recorded vendor payment against an open AP invoice (or, mixed, an AR one). */
    private static MAllocationHdr payablesAllocation(Properties in, Properties ctx, String trx) {
        MInvoice inv = new MInvoice(ctx, Integer.parseInt(in.getProperty("invoice_id")), trx);
        int payment = Integer.parseInt(in.getProperty("payment_id"));
        BigDecimal amount = new BigDecimal(in.getProperty("amount", inv.getGrandTotal().toPlainString()));
        Timestamp now = new Timestamp(System.currentTimeMillis());
        MAllocationHdr a = new MAllocationHdr(ctx, true, now, inv.getC_Currency_ID(),
                "Baobab Gate D synthetic payables allocation (CI only)", trx);
        a.setAD_Org_ID(inv.getAD_Org_ID());
        a.saveEx();
        // iDempiere signs payables negative on the allocation line.
        BigDecimal signed = inv.isSOTrx() ? amount : amount.negate();
        MAllocationLine l = new MAllocationLine(a, signed, BigDecimal.ZERO, BigDecimal.ZERO,
                inv.isSOTrx() ? inv.getGrandTotal().subtract(amount) : inv.getGrandTotal().subtract(amount).negate());
        l.setDocInfo(inv.getC_BPartner_ID(), 0, inv.getC_Invoice_ID());
        l.setPaymentInfo(payment, 0);
        l.saveEx();
        return a;
    }

    /** A payment selection header: the native remittance/bank-file path that must be refused for a placed client. */
    private static PO paySelection(Properties in, Properties ctx, String trx) {
        int bankAccount = DB.getSQLValueEx(null, "SELECT MIN(C_BankAccount_ID) FROM C_BankAccount WHERE AD_Client_ID=?"
                + " AND IsActive='Y'", CLIENT);
        MPaySelection ps = new MPaySelection(ctx, 0, trx);
        ps.setAD_Org_ID(org(in));
        ps.setC_BankAccount_ID(bankAccount);
        ps.setName("Baobab Gate D synthetic payment selection (CI only)");
        ps.setPayDate(new Timestamp(System.currentTimeMillis()));
        ps.saveEx();
        return ps;
    }

    /** ERP-B: a bank statement header, through the native model. Denied by name for a placed client. */
    private static PO bankStatement(Properties in, Properties ctx, String trx) {
        int bankAccount = DB.getSQLValueEx(null, "SELECT MIN(C_BankAccount_ID) FROM C_BankAccount WHERE AD_Client_ID=?"
                + " AND IsActive='Y'", CLIENT);
        MBankStatement st = new MBankStatement(new MBankAccount(ctx, bankAccount, trx));
        st.setAD_Org_ID(org(in));
        st.setName("Baobab Gate D synthetic bank statement (CI only)");
        st.saveEx();
        return st;
    }

    /** ERP-B: the org's cash journal for today, through the native model. Denied by name for a placed client. */
    private static PO cashJournal(Properties in, Properties ctx, String trx) {
        int currency = DB.getSQLValueEx(null, "SELECT C_Currency_ID FROM C_AcctSchema WHERE C_AcctSchema_ID="
                + "(SELECT C_AcctSchema1_ID FROM AD_ClientInfo WHERE AD_Client_ID=?)", CLIENT);
        MCash cash = MCash.get(ctx, org(in), new Timestamp(System.currentTimeMillis()), currency, trx);
        if (cash == null) throw new IllegalStateException("no cash book for the org");
        return cash;
    }

    /** ERP-B: a physical inventory header, through the native model. Denied by name for a placed client. */
    private static PO inventory(Properties in, Properties ctx, String trx) {
        int warehouse = DB.getSQLValueEx(null, "SELECT MIN(M_Warehouse_ID) FROM M_Warehouse WHERE AD_Client_ID=? AND AD_Org_ID=?"
                + " AND IsActive='Y'", CLIENT, org(in));
        MInventory inv = new MInventory(new MWarehouse(ctx, warehouse, trx), trx);
        inv.setDescription("Baobab Gate D synthetic physical inventory (CI only)");
        inv.saveEx();
        return inv;
    }
}
