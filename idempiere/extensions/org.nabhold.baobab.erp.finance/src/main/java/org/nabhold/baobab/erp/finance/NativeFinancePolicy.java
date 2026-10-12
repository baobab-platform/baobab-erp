package org.nabhold.baobab.erp.finance;

import java.util.Set;

/**
 * Synchronous BEFORE-save and BEFORE-document policy, not an EventAdmin
 * post-commit observer. Protected runtimes fail closed if the independent
 * authority port is absent, unavailable or rejects the exact native tuple.
 */
public final class NativeFinancePolicy {
    private static final Set<String> FINANCIAL_TABLES = Set.of(
            "C_Order", "C_OrderLine", "M_InOut", "M_InOutLine",
            "C_Invoice", "C_InvoiceLine", "C_Payment",
            "C_AllocationHdr", "C_AllocationLine", "C_BankStatement",
            "C_BankStatementLine", "C_BankAccount", "C_Cash",
            "C_CashLine", "Fact_Acct", "C_AcctSchema",
            "C_ElementValue", "C_ValidCombination", "C_Tax", "C_TaxAcct",
            "GL_Journal", "GL_JournalLine", "M_Cost", "M_CostDetail");

    private NativeFinancePolicy() {}

    public static boolean protectedRuntime(String environment) {
        return environment == null || !Set.of("test", "development", "integration").contains(environment);
    }

    public static String requireBeforeMutation(
            String table, int client, int org, int nativeId, String action,
            String trxName, boolean protectedRuntime, NativeFinancialAuthority provider) {
        if (!FINANCIAL_TABLES.contains(table)) {
            return null;
        }
        if (!protectedRuntime) {
            return null; // only explicitly configured isolated synthetic local test runtimes
        }
        if (client <= 0 || org <= 0 || nativeId < 0
                || action == null || action.isBlank() || trxName == null
                || trxName.isBlank() || provider == null) {
            return "BAOBAB_NATIVE_FINANCE_DENIED: current CP/IAM/financial authority unavailable";
        }
        try {
            if (provider.currentlyAuthorised(table, client, org, nativeId, action, trxName)) {
                return null;
            }
        } catch (RuntimeException unavailable) {
            // Intentionally do not include the possibly sensitive exception in the veto.
        }
        return "BAOBAB_NATIVE_FINANCE_DENIED: operation-specific native authority denied";
    }

    public static Set<String> protectedTables() {
        return FINANCIAL_TABLES;
    }
}
