package org.nabhold.baobab.erp.finance;

/**
 * Trusted in-process bridge to a CP-issued RUNTIME Context for the SAME IAM
 * workload that will call CP. It cannot be supplied by a UI, HTTP header,
 * document PO field or arbitrary JVM property.
 */
public interface NativeFinancialContextSource {
    NativeLease currentLease(String table, int adClientId, int adOrgId,
                             int recordId, String action, String transactionName);

    record NativeLease(String tenantId, String contextId, String organisationId,
                       String expectedLegalEntityId, String market,
                       String role, String activity, String capability) {}
}
