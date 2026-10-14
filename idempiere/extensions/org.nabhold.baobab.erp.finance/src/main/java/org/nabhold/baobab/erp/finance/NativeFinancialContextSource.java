package org.nabhold.baobab.erp.finance;

/**
 * Trusted in-process source of the ERP-owned native placement that applies
 * to a classified operation (ADR-ERP-022). It reads only governed placement
 * and document provenance on the SAME native transaction. It cannot be
 * supplied by a UI, HTTP header, document PO field or arbitrary JVM property,
 * and it never confers authority: CP decides that per operation.
 */
public interface NativeFinancialContextSource {
    /** The in-force placement for the operation, or null when none applies unambiguously. */
    NativePlacement currentPlacement(NativeOperation operation);
}
