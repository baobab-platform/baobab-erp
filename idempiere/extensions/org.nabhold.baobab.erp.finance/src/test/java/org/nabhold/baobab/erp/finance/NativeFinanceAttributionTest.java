package org.nabhold.baobab.erp.finance;

import static org.junit.jupiter.api.Assertions.*;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class NativeFinanceAttributionTest {
    private static final NativeFinancialContextSource.NativeLease LEASE =
            new NativeFinancialContextSource.NativeLease(
                "tn_synthetic","0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
                "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
                "LE-SYNTHETIC-ZA","ZA",
                "INVOICE_ISSUER","B2B_INVOICE","erp.invoice.post");

    @Test
    void appendUsesExactlyNativeTransactionAndNeverCommitsOrClosesIt() throws Exception {
        AtomicInteger executions = new AtomicInteger();
        AtomicInteger connectionCommits = new AtomicInteger();
        AtomicInteger preparedParameters = new AtomicInteger();
        PreparedStatement statement = (PreparedStatement) Proxy.newProxyInstance(
                getClass().getClassLoader(), new Class<?>[]{PreparedStatement.class}, (obj,method,args)-> {
                    if (method.getName().startsWith("set")) {
                        preparedParameters.incrementAndGet();
                        return null;
                    }
                    if (method.getName().equals("executeUpdate")) {
                        executions.incrementAndGet();
                        return 1;
                    }
                    if (method.getName().equals("close")) return null;
                    return null;
                });
        Connection connection = (Connection) Proxy.newProxyInstance(
                getClass().getClassLoader(), new Class<?>[]{Connection.class}, (obj,method,args)-> {
                    return switch (method.getName()) {
                        case "getAutoCommit" -> false;
                        case "prepareStatement" -> statement;
                        case "commit", "rollback", "close" -> {
                            connectionCommits.incrementAndGet();
                            yield null;
                        }
                        default -> null;
                    };
                });
        NativeFinanceAttribution ledger = new NativeFinanceAttribution(trx -> {
            assertEquals("native-transaction-synthetic", trx);
            return connection;
        });
        ledger.append("C_Invoice",100,200,300,"document:TIMING_BEFORE_COMPLETE",
                "native-transaction-synthetic",LEASE,
                "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d","cp/evidence/synthetic");
        assertEquals(1,executions.get());
        assertEquals(13,preparedParameters.get());
        assertEquals(0,connectionCommits.get(),"ledger must not independently commit/rollback/close native Trx");
    }

    @Test
    void autocommitAndMalformedMandateFailBeforeMutation() {
        Connection autocommit = (Connection)Proxy.newProxyInstance(
                getClass().getClassLoader(),new Class<?>[]{Connection.class},(o,m,a)->{
                    if (m.getName().equals("getAutoCommit")) return true;
                    return null;
                });
        NativeFinanceAttribution ledger = new NativeFinanceAttribution(t->autocommit);
        assertThrows(IllegalStateException.class, () -> ledger.append(
                "C_Payment",101,202,333,"document:TIMING_BEFORE_COMPLETE","native-trx",
                LEASE,"0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d","cp/evidence/synthetic"));
        assertThrows(IllegalArgumentException.class, () -> ledger.append(
                "C_Payment",101,202,333,"document:TIMING_BEFORE_COMPLETE","native-trx",
                LEASE,"forged-mandate","cp/evidence/synthetic"));
    }
}
