package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/** No live client, legal entity, tax approval or certificate is simulated as real. */
class NativeFinancePolicyTest {
    private static NativeRecord record(String table, int client, int org, int id, String action, String trx) {
        return new NativeRecord(table, client, org, id, action, trx, column -> null);
    }

    @Test
    void directNativeCreateUpdateDeleteAndPostingFailWithoutTrustedProvider() {
        for (String table : NativeFinancePolicy.protectedTables()) {
            for (String action : new String[] {
                    "model:TYPE_BEFORE_NEW", "model:TYPE_BEFORE_CHANGE",
                    "model:TYPE_BEFORE_DELETE", "document:TIMING_BEFORE_COMPLETE",
                    "document:TIMING_BEFORE_POST", "document:TIMING_BEFORE_REVERSEACCRUAL"
            }) {
                assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                        record(table, 101, 202, 1234, action, "trx-1"), true, null));
            }
        }
    }

    @Test
    void unknownAndProtectedDeploymentStatesAreNotLocal() {
        for (String env : new String[] {"staging", "production", "STAGING", "local", ""}) {
            assertTrue(NativeFinancePolicy.protectedRuntime(env));
        }
        assertTrue(NativeFinancePolicy.protectedRuntime(null));
        assertFalse(NativeFinancePolicy.protectedRuntime("test"));
        assertFalse(NativeFinancePolicy.protectedRuntime("development"));
    }

    @Test
    void onlyCurrentExactIndependentAuthorityCanPermitNativeMutation() {
        AtomicInteger calls = new AtomicInteger();
        NativeFinancialAuthority authority = r -> {
            calls.incrementAndGet();
            return r.table().equals("C_Invoice") && r.adClientId() == 111 && r.adOrgId() == 222
                    && r.recordId() == 1234
                    && r.action().equals("document:TIMING_BEFORE_POST")
                    && r.transactionName().equals("trusted-trx-7");
        };
        assertNull(NativeFinancePolicy.requireBeforeMutation(
                record("C_Invoice", 111, 222, 1234, "document:TIMING_BEFORE_POST", "trusted-trx-7"), true, authority));
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                record("C_Invoice", 111, 333, 1234, "document:TIMING_BEFORE_POST", "trusted-trx-7"), true, authority));
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                record("C_Payment", 111, 222, 1234, "document:TIMING_BEFORE_POST", "trusted-trx-7"), true, authority));
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                record("C_Invoice", 111, 222, 1234, "document:TIMING_BEFORE_POST", "trusted-trx-7"), true, r -> { throw new IllegalStateException("CP offline"); }));
        assertTrue(calls.get() >= 3);
    }

    @Test
    void malformedNativeContextCannotBeAuthorizedByExternalProvider() {
        NativeFinancialAuthority alwaysYes = r -> true;
        for (int[] bad : new int[][] {{0,202,11},{111,0,11},{111,202,-1}}) {
            assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                    record("C_Order", bad[0], bad[1], bad[2], "model:TYPE_BEFORE_NEW", "trx-1"), true, alwaysYes));
        }
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                record("C_Order", 111, 222, 11, "model:TYPE_BEFORE_NEW", ""), true, alwaysYes));
        assertTrue(NativeFinancePolicy.protectedTables().contains("Fact_Acct"));
        assertTrue(NativeFinancePolicy.protectedTables().contains("C_BankAccount"));
    }
}
