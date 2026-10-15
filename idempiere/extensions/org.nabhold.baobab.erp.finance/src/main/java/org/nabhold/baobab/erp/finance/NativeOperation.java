package org.nabhold.baobab.erp.finance;

/**
 * A native write classified into exactly one catalogued Shared erp/v2
 * operation class (ADR-SHARED-034) and attributed to its SOURCE document:
 * a line to its header, a ledger line to the document it posts. A source
 * record id of 0 means a header being created in this transaction.
 */
public record NativeOperation(String operationClass, String sourceTable, int sourceRecordId,
                              NativeRecord record) {
    public static final String GL_JOURNAL = "erp.gl-journal.post";
    public static final String CUSTOMER_INVOICE = "erp.customer-invoice.issue";
    public static final String PAYMENT = "erp.payment.record";
    public static final String ALLOCATION = "erp.allocation.record";
    public static final String SHIPMENT = "erp.shipment.complete";
    public static final String SALES_ORDER = "erp.sales-order.complete";
    // Shared erp/v2 catalogue version 2 (ADR-SHARED-037): purchase-side and
    // vendor-payment RECORDING classes; never money-movement authority.
    public static final String PURCHASE_ORDER = "erp.purchase-order.complete";
    public static final String MATERIAL_RECEIPT = "erp.material-receipt.complete";
    public static final String VENDOR_INVOICE = "erp.vendor-invoice.record";
    public static final String VENDOR_PAYMENT = "erp.vendor-payment.record";
    public static final String PAYABLES_ALLOCATION = "erp.payables-allocation.record";

    /** Exact operation and transaction reference bound into every CP decision. */
    public String operationReference() {
        String raw = "erp/" + operationClass + "/" + sourceTable + "/" + sourceRecordId + "/"
                + record.table() + "/" + record.recordId() + "/" + record.action() + "/" + record.transactionName();
        StringBuilder out = new StringBuilder(raw.length());
        for (char c : raw.toCharArray()) out.append(c >= 0x21 && c <= 0x7E ? c : '_');
        return out.length() > 256 ? null : out.toString();
    }
}
