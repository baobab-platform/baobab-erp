package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

/**
 * Immutably appends the exact CP-authorised actor, decision, mandate lineage,
 * placement and Finance baseline to the SAME native iDempiere JDBC transaction,
 * or DENIES (ADR-BCP-027 §10.2, ADR-ERP-022). No separate baobab-app
 * connection: a separate commit would produce orphan audit statements after
 * rollbacks. The database independently refuses expired authority and an
 * attribution that does not match the in-force placement.
 */
final class NativeFinanceAttribution {
    private static final String INSERT = """
        INSERT INTO baobab_native.finance_authority_attribution
        (tenant_id, context_id, operating_organisation_id,
         responsible_legal_entity_id, cp_mandate_id, evidence_reference,
         native_table, ad_client_id, ad_org_id, native_record_id,
         action_name, native_transaction_name, correlation_id,
         decision_id, operation_class, source_table, source_record_id,
         supersedes_mandate_id, mandate_effective_from, authority_expires_at,
         placement_id, placement_version,
         finance_baseline_legal_entity_id, finance_baseline_version)
        VALUES (?,?::uuid,?::uuid,?,?::uuid,?,?,?,?,?,?,?,?::uuid,
                ?::uuid,?,?,?,?::uuid,?,?,?::uuid,?,?,?)
        """;
    private static final String CURRENT =
            "SELECT baobab_native.has_current_attribution(?, ?, ?)";

    /** A CP posting-authority decision ERP has already validated. */
    record Decision(String decisionId, String contextId, String mandateId, String supersedesMandateId,
                    String evidenceReference, Instant mandateEffectiveFrom, Instant usableUntil) {}

    private final NativeConnections connections;

    NativeFinanceAttribution(NativeConnections connections) {
        this.connections = connections;
    }

    /** True when this transaction already holds current authority for the source document. */
    boolean hasCurrent(NativeOperation operation) throws Exception {
        if (operation.sourceRecordId() <= 0) return false;
        Connection db = NativeConnections.transactional(connections, operation.record().transactionName());
        try (PreparedStatement s = db.prepareStatement(CURRENT)) {
            s.setInt(1, operation.record().adClientId());
            s.setString(2, operation.sourceTable());
            s.setInt(3, operation.sourceRecordId());
            try (ResultSet r = s.executeQuery()) {
                return r.next() && r.getBoolean(1);
            }
        }
    }

    void append(NativeOperation operation, NativePlacement placement, Decision decision,
                NativeFinanceReadiness.FinanceBaseline baseline) throws Exception {
        NativeRecord record = operation.record();
        if (decision == null || baseline == null || placement == null
                || decision.evidenceReference() == null || decision.evidenceReference().isBlank()
                || !placement.legalEntityId().equals(baseline.legalEntityId())) {
            throw new IllegalArgumentException("native financial attribution is unbound");
        }
        UUID.fromString(decision.decisionId());
        UUID.fromString(decision.contextId());
        UUID.fromString(decision.mandateId());
        UUID.fromString(placement.operatingOrganisationId());
        UUID.fromString(placement.placementId());
        // Transaction scoping: never close/commit this connection here.
        Connection db = NativeConnections.transactional(connections, record.transactionName());
        try (PreparedStatement s = db.prepareStatement(INSERT)) {
            s.setString(1, placement.tenantId());
            s.setString(2, decision.contextId());
            s.setString(3, placement.operatingOrganisationId());
            s.setString(4, placement.legalEntityId());
            s.setString(5, decision.mandateId());
            s.setString(6, decision.evidenceReference());
            s.setString(7, record.table());
            s.setInt(8, record.adClientId());
            s.setInt(9, record.adOrgId());
            s.setInt(10, Math.max(record.recordId(), 0));
            s.setString(11, record.action());
            s.setString(12, record.transactionName());
            s.setString(13, UUID.randomUUID().toString());
            s.setString(14, decision.decisionId());
            s.setString(15, operation.operationClass());
            s.setString(16, operation.sourceTable());
            s.setInt(17, operation.sourceRecordId());
            s.setString(18, decision.supersedesMandateId());
            s.setTimestamp(19, Timestamp.from(decision.mandateEffectiveFrom()));
            s.setTimestamp(20, Timestamp.from(decision.usableUntil()));
            s.setString(21, placement.placementId());
            s.setInt(22, placement.version());
            s.setString(23, baseline.legalEntityId());
            s.setInt(24, baseline.version());
            if (s.executeUpdate() != 1) {
                throw new SQLException("native financial authority audit was not recorded");
            }
        }
    }
}
