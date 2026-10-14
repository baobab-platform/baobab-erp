package org.nabhold.baobab.erp.finance;

/** Independent native company, accounting period and Finance baseline
 * evidence (ADR-ERP-008). CP legal actor/documentary decisions can NEVER
 * implement this requirement by themselves.
 */
public interface NativeFinanceReadiness {
    /** The Finance baseline in force for the placement's legal entity, or null when not ready. */
    FinanceBaseline currentBaseline(NativeOperation operation, NativePlacement placement);

    record FinanceBaseline(String legalEntityId, int version) {}
}
