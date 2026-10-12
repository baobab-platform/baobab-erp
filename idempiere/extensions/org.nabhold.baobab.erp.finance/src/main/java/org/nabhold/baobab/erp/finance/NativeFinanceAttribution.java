package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.util.UUID;

/**
 * Immutably appends the exact CP-checked actor+operation to the SAME native
 * iDempiere JDBC transaction, or DENIES. No separate baobab-app connection:
 * a separate commit would produce orphan audit statements after rollbacks.
 */
final class NativeFinanceAttribution {
    private static final String INSERT = """
        INSERT INTO baobab_native.finance_authority_attribution
        (tenant_id, context_id, operating_organisation_id,
         responsible_legal_entity_id, cp_mandate_id, evidence_reference,
         native_table, ad_client_id, ad_org_id, native_record_id,
         action_name, native_transaction_name, correlation_id)
        VALUES (?,?::uuid,?::uuid,?,?::uuid,?,?,?,?,?,?,?,?::uuid)
        """;

    @FunctionalInterface
    interface ConnectionProvider {
        Connection forNativeTransaction(String transactionName) throws Exception;
    }

    static final ConnectionProvider NATIVE_TRANSACTION_CONNECTION = name -> {
        Class<?> nativeTrx = Class.forName("org.compiere.util.Trx");
        Object current = nativeTrx.getMethod("get", String.class, boolean.class)
                .invoke(null, name, false);
        if (current == null) {
            throw new IllegalStateException("iDempiere native transaction is unavailable");
        }
        return (Connection) nativeTrx.getMethod("getConnection").invoke(current);
    };

    private final ConnectionProvider connectionProvider;

    NativeFinanceAttribution(ConnectionProvider connectionProvider) {
        this.connectionProvider = connectionProvider;
    }

    void append(String table, int client, int org, int nativeId, String action,
                String trx, NativeFinancialContextSource.NativeLease lease,
                String cpMandate, String evidenceReference) throws Exception {
        if (trx == null || trx.isBlank() || nativeId < 0
                || cpMandate == null || evidenceReference == null
                || evidenceReference.isBlank()) {
            throw new IllegalArgumentException("native financial attribution is unbound");
        }
        UUID context = UUID.fromString(lease.contextId());
        UUID organisation = UUID.fromString(lease.organisationId());
        UUID mandate = UUID.fromString(cpMandate);
        // Transaction scoping: never close/commit this connection here.
        Connection db = connectionProvider.forNativeTransaction(trx);
        if (db == null || db.getAutoCommit()) {
            throw new IllegalStateException("native financial transaction is not atomic");
        }
        try (PreparedStatement statement = db.prepareStatement(INSERT)) {
            statement.setString(1, lease.tenantId());
            statement.setString(2, context.toString());
            statement.setString(3, organisation.toString());
            statement.setString(4, lease.expectedLegalEntityId());
            statement.setString(5, mandate.toString());
            statement.setString(6, evidenceReference);
            statement.setString(7, table);
            statement.setInt(8, client);
            statement.setInt(9, org);
            statement.setInt(10, nativeId);
            statement.setString(11, action);
            statement.setString(12, trx);
            statement.setString(13, UUID.randomUUID().toString());
            if (statement.executeUpdate() != 1) {
                throw new SQLException("native financial authority audit was not recorded");
            }
        }
    }
}
