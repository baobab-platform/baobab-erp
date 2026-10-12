package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/** No live client, legal entity, tax approval or certificate is simulated as real. */
class NativeFinancePolicyTest {
    @Test
    void directNativeCreateUpdateDeleteAndPostingFailWithoutTrustedProvider() {
        for (String table : NativeFinancePolicy.protectedTables()) {
            for (String action : new String[] {
                    "model:TYPE_BEFORE_NEW", "model:TYPE_BEFORE_CHANGE",
                    "model:TYPE_BEFORE_DELETE", "document:TIMING_BEFORE_COMPLETE",
                    "document:TIMING_BEFORE_POST", "document:TIMING_BEFORE_REVERSEACCRUAL"
            }) {
                assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                        table, 101, 202, 1234, action, "trx-1", true, null));
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
        NativeFinancialAuthority authority = (table, client, org, recordId, action, trx) -> {
            calls.incrementAndGet();
            return table.equals("C_Invoice") && client == 111 && org == 222
                    && recordId == 1234
                    && action.equals("document:TIMING_BEFORE_POST")
                    && trx.equals("trusted-trx-7");
        };
        assertNull(NativeFinancePolicy.requireBeforeMutation(
                "C_Invoice", 111, 222, 1234, "document:TIMING_BEFORE_POST",
                "trusted-trx-7", true, authority));
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                "C_Invoice", 111, 333, 1234, "document:TIMING_BEFORE_POST",
                "trusted-trx-7", true, authority));
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                "C_Payment", 111, 222, 1234, "document:TIMING_BEFORE_POST",
                "trusted-trx-7", true, authority));
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                "C_Invoice", 111, 222, 1234, "document:TIMING_BEFORE_POST",
                "trusted-trx-7", true, (t,c,o,id,a,x) -> { throw new IllegalStateException("CP offline"); }));
        assertTrue(calls.get() >= 3);
    }

    @Test
    void malformedNativeContextCannotBeAuthorizedByExternalProvider() {
        NativeFinancialAuthority alwaysYes = (t,c,o,id,a,trx) -> true;
        for (int[] bad : new int[][] {{0,202,11},{111,0,11},{111,202,-1}}) {
            assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                    "C_Order", bad[0], bad[1], bad[2], "model:TYPE_BEFORE_NEW",
                    "trx-1", true, alwaysYes));
        }
        assertNotNull(NativeFinancePolicy.requireBeforeMutation(
                "C_Order", 111, 222, 11, "model:TYPE_BEFORE_NEW", "", true, alwaysYes));
        assertTrue(NativeFinancePolicy.protectedTables().contains("Fact_Acct"));
        assertTrue(NativeFinancePolicy.protectedTables().contains("C_BankAccount"));
    }
}
