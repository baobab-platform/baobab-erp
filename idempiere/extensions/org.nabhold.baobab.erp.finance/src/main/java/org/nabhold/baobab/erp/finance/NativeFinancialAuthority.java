package org.nabhold.baobab.erp.finance;

/**
 * Independent, trusted OSGi authority port. Only a platform-owned provider
 * backed by authenticated live CP/IAM/legal-actor/documentary and certified
 * iDempiere company/period/tax checks may implement this contract.
 * Native record data, JVM properties, UI sessions and caller-provided
 * HTTP headers MUST NOT be treated as authority evidence.
 */
public interface NativeFinancialAuthority {
    boolean currentlyAuthorised(
            String table, int adClientId, int adOrgId, int nativeRecordId,
            String action, String transactionName);
}
