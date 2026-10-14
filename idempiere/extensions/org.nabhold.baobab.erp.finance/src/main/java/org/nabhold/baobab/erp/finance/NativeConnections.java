package org.nabhold.baobab.erp.finance;

import java.sql.Connection;

/** Resolves the JDBC connection of the iDempiere transaction a callback runs in. */
@FunctionalInterface
interface NativeConnections {
    Connection forNativeTransaction(String transactionName) throws Exception;

    /** The connection of the named live iDempiere Trx; never a separate pool connection. */
    NativeConnections IDEMPIERE = name -> {
        Class<?> nativeTrx = Class.forName("org.compiere.util.Trx");
        Object current = nativeTrx.getMethod("get", String.class, boolean.class).invoke(null, name, false);
        if (current == null) {
            throw new IllegalStateException("iDempiere native transaction is unavailable");
        }
        return (Connection) nativeTrx.getMethod("getConnection").invoke(current);
    };

    /** Same transaction or nothing: an autocommit connection cannot be atomic with the mutation. */
    static Connection transactional(NativeConnections connections, String trx) throws Exception {
        if (trx == null || trx.isBlank()) throw new IllegalArgumentException("native transaction required");
        Connection db = connections.forNativeTransaction(trx);
        if (db == null || db.getAutoCommit()) {
            throw new IllegalStateException("native financial transaction is not atomic");
        }
        return db;
    }
}
