package org.nabhold.baobab.erp.finance;

/** Independent native company, accounting period, tax and finance baseline
 * evidence. CP legal actor/documentary decisions can NEVER implement this
 * requirement by themselves.
 */
public interface NativeFinanceReadiness {
    boolean currentCompanyFinanceReady(
            String table, int adClientId, int adOrgId, int nativeRecordId,
            String action, String transactionName, String legalEntityId);
}
