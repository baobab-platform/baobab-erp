package org.nabhold.baobab.erp.finance;

import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.Date;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * ADR-SHARED-033 F1: transaction-consistent, read-only source of native posted
 * ledger facts. This is NOT a finance.ledger.read provider or HTTP endpoint.
 * The calling resource server must independently implement current IAM/CP
 * operation-specific permission and construct a trusted Scope; a RUNTIME
 * PlatformContext alone is insufficient to select a LegalEntity/book.
 *
 * A missing mandate, native placement, book, FinanceBaseline, per-source
 * attribution, historical lineage or repeatable-read snapshot fails closed.
 * The bounded read returns only actual Fact_Acct rows, never synthetic totals,
 * unposted GL_Journal drafts or inferred currency conversions. Pagination,
 * financial statement reconciliation and certified completeness are separate
 * F1 work and cannot be claimed from this component.
 */
final class NativeLedgerFacts {
    static final int MAX_FACTS = 1000;
    private static final String PLACEMENT = """
        SELECT p.placement_id
          FROM baobab_native.native_placement p
          JOIN adempiere.ad_client c ON c.ad_client_id = p.ad_client_id AND c.isactive = 'Y'
          JOIN adempiere.ad_org o ON o.ad_org_id = p.ad_org_id
                                AND o.ad_client_id = p.ad_client_id AND o.isactive = 'Y'
         WHERE p.tenant_id = ? AND p.legal_entity_id = ?
           AND p.operating_organisation_id::text = ?
           AND p.ad_client_id = ? AND p.ad_org_id = ?
           AND p.effective_from <= clock_timestamp()
           AND (p.effective_to IS NULL OR p.effective_to > clock_timestamp())
         LIMIT 2 FOR SHARE OF p
        """;
    private static final String BOOK = """
        SELECT 1 FROM adempiere.c_acctschema s
          JOIN adempiere.c_currency u ON u.c_currency_id = s.c_currency_id
         WHERE s.c_acctschema_id = ? AND s.ad_client_id = ?
           AND s.isactive = 'Y' AND u.iso_code = ?
        """;
    private static final String CURRENT_BASELINE = """
        SELECT b.functional_currency, b.version,
          EXISTS (SELECT 1 FROM baobab.financial_configuration_baseline_withdrawal w
                   WHERE w.legal_entity_id = b.legal_entity_id AND w.version = b.version)
          FROM baobab.financial_configuration_baseline b
         WHERE b.legal_entity_id = ? AND b.effective_from <= current_date
         ORDER BY b.effective_from DESC, b.version DESC
         LIMIT 1
        """;
    private static final String FACTS = """
        SELECT f.fact_acct_id, f.dateacct, f.account_id,
               f.amtacctdr, f.amtacctcr, f.ad_table_id, f.record_id,
               f.ad_client_id, f.ad_org_id
          FROM adempiere.fact_acct f
         WHERE f.ad_client_id = ? AND f.ad_org_id = ? AND f.c_acctschema_id = ?
           AND f.dateacct >= ? AND f.dateacct <= ?
           AND f.created <= ?
         ORDER BY f.dateacct, f.fact_acct_id
         LIMIT ?
        """;
    private static final String LINEAGE = """
        SELECT DISTINCT a.finance_baseline_version
          FROM adempiere.ad_table t
          CROSS JOIN LATERAL baobab_native.governed_root(t.tablename, ?) root
          JOIN baobab_native.finance_authority_attribution a
            ON lower(a.source_table) = lower(root.root_table)
           AND a.source_record_id = root.root_record
          JOIN baobab.financial_configuration_baseline b
            ON b.legal_entity_id = a.finance_baseline_legal_entity_id
           AND b.version = a.finance_baseline_version
         WHERE t.ad_table_id = ?
           AND a.tenant_id = ? AND a.responsible_legal_entity_id = ?
           AND a.operating_organisation_id::text = ?
           AND a.ad_client_id = ? AND a.ad_org_id = ?
           AND b.legal_entity_id = ? AND b.functional_currency = ?
         LIMIT 2
        """;

    record Scope(String tenantId, String legalEntityId, String operatingOrganisationId,
                 int clientId, int orgId, int accountingSchemaId, String currency,
                 LocalDate periodStart, LocalDate periodEnd, Instant asOf) {
        Scope {
            if (tenantId == null || tenantId.isBlank()
                    || legalEntityId == null || legalEntityId.isBlank()
                    || operatingOrganisationId == null || operatingOrganisationId.isBlank()
                    || clientId <= 0 || orgId <= 0 || accountingSchemaId <= 0
                    || currency == null || !currency.matches("[A-Z]{3}")
                    || periodStart == null || periodEnd == null || periodEnd.isBefore(periodStart)
                    || asOf == null || asOf.isAfter(Instant.now().plusSeconds(1))) {
                throw new IllegalArgumentException("invalid trusted finance read scope");
            }
        }
    }

    /** External operation-specific current permit is mandatory and never inferred from the scope object. */
    @FunctionalInterface
    interface CurrentAuthority {
        boolean permits(Scope scope) throws Exception;
    }

    record Fact(int nativeFactId, LocalDate accountingDate, int nativeAccountId,
                BigDecimal debit, BigDecimal credit, int historicalBaselineVersion) {}
    record Readback(List<Fact> facts) {
        Readback { facts = List.copyOf(facts); }
    }

    /** Never changes the connection's transaction state, commits, or publishes financial data. */
    Readback read(Connection db, Scope scope, CurrentAuthority authority) throws Exception {
        Objects.requireNonNull(scope, "trusted scope required");
        if (authority == null || !authority.permits(scope)) {
            throw new SecurityException("current finance read authority is not established");
        }
        if (db == null || db.getAutoCommit() || (db.getTransactionIsolation() != Connection.TRANSACTION_REPEATABLE_READ
                && db.getTransactionIsolation() != Connection.TRANSACTION_SERIALIZABLE)) {
            throw new SecurityException("native ledger needs one consistent database transaction");
        }
        if (!hasUniquePlacement(db, scope) || !hasBook(db, scope) || !hasCurrentBaseline(db, scope)) {
            throw new SecurityException("native placement, book or Finance baseline unavailable");
        }
        List<Fact> facts = new ArrayList<>();
        try (PreparedStatement s = db.prepareStatement(FACTS)) {
            s.setInt(1, scope.clientId());
            s.setInt(2, scope.orgId());
            s.setInt(3, scope.accountingSchemaId());
            s.setDate(4, Date.valueOf(scope.periodStart()));
            s.setDate(5, Date.valueOf(scope.periodEnd()));
            s.setTimestamp(6, Timestamp.from(scope.asOf()));
            s.setInt(7, MAX_FACTS + 1);
            try (ResultSet r = s.executeQuery()) {
                while (r.next()) {
                    if (facts.size() == MAX_FACTS) {
                        throw new SecurityException("unpaged ledger scope exceeds bounded read; no partial total");
                    }
                    int clientId = r.getInt(8);
                    int orgId = r.getInt(9);
                    if (clientId != scope.clientId() || orgId != scope.orgId()) {
                        throw new SecurityException("native ledger row changed scope");
                    }
                    int baseline = historicalBaseline(db, scope, r.getInt(6), r.getInt(7));
                    BigDecimal dr = r.getBigDecimal(4), cr = r.getBigDecimal(5);
                    if (dr == null || cr == null || r.getDate(2) == null || r.getInt(3) <= 0) {
                        throw new SecurityException("incomplete native accounting fact");
                    }
                    facts.add(new Fact(r.getInt(1), r.getDate(2).toLocalDate(), r.getInt(3), dr, cr, baseline));
                }
            }
        }
        return new Readback(facts);
    }

    private boolean hasUniquePlacement(Connection db, Scope s) throws Exception {
        try (PreparedStatement st = db.prepareStatement(PLACEMENT)) {
            st.setString(1, s.tenantId());
            st.setString(2, s.legalEntityId());
            st.setString(3, s.operatingOrganisationId());
            st.setInt(4, s.clientId());
            st.setInt(5, s.orgId());
            try (ResultSet rows = st.executeQuery()) {
                return rows.next() && !rows.next();
            }
        }
    }

    private boolean hasBook(Connection db, Scope s) throws Exception {
        try (PreparedStatement st = db.prepareStatement(BOOK)) {
            st.setInt(1, s.accountingSchemaId());
            st.setInt(2, s.clientId());
            st.setString(3, s.currency());
            try (ResultSet rows = st.executeQuery()) {
                return rows.next() && !rows.next();
            }
        }
    }

    private boolean hasCurrentBaseline(Connection db, Scope s) throws Exception {
        try (PreparedStatement st = db.prepareStatement(CURRENT_BASELINE)) {
            st.setString(1, s.legalEntityId());
            try (ResultSet rows = st.executeQuery()) {
                return rows.next() && s.currency().equals(rows.getString(1)) && rows.getInt(2) > 0
                        && !rows.getBoolean(3);
            }
        }
    }

    private int historicalBaseline(Connection db, Scope s, int tableId, int recordId) throws Exception {
        try (PreparedStatement st = db.prepareStatement(LINEAGE)) {
            // Use the exact native source-to-governed-root resolver enforced
            // by N0006's Fact_Acct COMMIT fence (M_MatchInv/PO included).
            st.setInt(1, recordId);
            st.setInt(2, tableId);
            st.setString(3, s.tenantId());
            st.setString(4, s.legalEntityId());
            st.setString(5, s.operatingOrganisationId());
            st.setInt(6, s.clientId());
            st.setInt(7, s.orgId());
            st.setString(8, s.legalEntityId());
            st.setString(9, s.currency());
            try (ResultSet rows = st.executeQuery()) {
                if (!rows.next()) throw new SecurityException("historical native ledger lineage unavailable");
                int version = rows.getInt(1);
                if (version <= 0 || rows.next()) throw new SecurityException("ambiguous native ledger lineage");
                return version;
            }
        }
    }
}
