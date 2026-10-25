package org.nabhold.baobab.erp.finance;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

/**
 * Platform-owned {@link NativeFinancialContextSource} backed by the governed
 * baobab_native placement registry and document provenance (ADR-ERP-022),
 * read on the SAME native transaction with FOR SHARE so a concurrent placement
 * closure serialises with the posting.
 *
 * <ul>
 *   <li>A header being created uses the placement in force for its AD_Org.</li>
 *   <li>Any other write uses the placement recorded when its source document was
 *       created. That version, or a later version of the SAME placement with an
 *       unchanged tenant, Organisation, legal entity, market and native org, must
 *       be in force now. Anything else is ambiguous and returns null.</li>
 * </ul>
 */
final class PlacementContextSource implements NativeFinancialContextSource {
    private static final String COLUMNS = """
        p.placement_id::text, p.version, p.tenant_id, p.engine_instance_id,
        p.operating_organisation_id::text, p.legal_entity_id, p.market, p.ad_client_id, p.ad_org_id
        """;
    private static final String CURRENT_FOR_ORG = "SELECT " + COLUMNS + """
          FROM baobab_native.native_placement p
          JOIN adempiere.ad_org o ON o.ad_org_id = p.ad_org_id
             AND o.ad_client_id = p.ad_client_id AND o.isactive = 'Y'
         WHERE p.ad_client_id = ? AND p.ad_org_id = ?
           AND p.effective_from <= clock_timestamp()
           AND (p.effective_to IS NULL OR p.effective_to > clock_timestamp())
         FOR SHARE OF p
        """;
    private static final String CURRENT_FOR_PROVENANCE = "SELECT " + COLUMNS + """
          FROM baobab_native.document_provenance d
          JOIN baobab_native.native_placement origin
            ON origin.placement_id = d.placement_id AND origin.version = d.placement_version
          JOIN baobab_native.native_placement p
            ON p.placement_id = origin.placement_id
           AND p.version >= origin.version
           AND p.effective_from <= clock_timestamp()
           AND (p.effective_to IS NULL OR p.effective_to > clock_timestamp())
           AND (p.tenant_id, p.operating_organisation_id, p.legal_entity_id, p.market, p.ad_client_id, p.ad_org_id)
               = (origin.tenant_id, origin.operating_organisation_id, origin.legal_entity_id, origin.market,
                  origin.ad_client_id, origin.ad_org_id)
          JOIN adempiere.ad_org o ON o.ad_org_id = p.ad_org_id
             AND o.ad_client_id = p.ad_client_id AND o.isactive = 'Y'
         WHERE d.native_table = ? AND d.record_id = ? AND d.ad_client_id = ?
           AND (? = false OR d.ad_org_id = ?)
         FOR SHARE OF p, d
        """;

    private final NativeConnections connections;

    PlacementContextSource(NativeConnections connections) {
        this.connections = connections;
    }

    @Override
    public NativePlacement currentPlacement(NativeOperation operation) {
        if (operation == null) return null;
        NativeRecord record = operation.record();
        try {
            Connection db = NativeConnections.transactional(connections, record.transactionName());
            PreparedStatement statement;
            if (operation.sourceRecordId() == 0) {
                if (!operation.sourceTable().equals(record.table())) return null;
                statement = db.prepareStatement(CURRENT_FOR_ORG);
                statement.setInt(1, record.adClientId());
                statement.setInt(2, record.adOrgId());
            } else {
                statement = db.prepareStatement(CURRENT_FOR_PROVENANCE);
                statement.setString(1, operation.sourceTable());
                statement.setInt(2, operation.sourceRecordId());
                statement.setInt(3, record.adClientId());
                // A governed header must still have its creation-time AD_Org.
                // Its child/ledger rows can legitimately use another AD_Org,
                // so for those the source document remains the authority.
                statement.setBoolean(4, operation.sourceTable().equals(record.table())
                        && operation.sourceRecordId() == record.recordId());
                statement.setInt(5, record.adOrgId());
            }
            try (statement; ResultSet r = statement.executeQuery()) {
                if (!r.next()) return null;
                NativePlacement placement = new NativePlacement(r.getString(1), r.getInt(2), r.getString(3),
                        r.getString(4), r.getString(5), r.getString(6), r.getString(7), r.getInt(8), r.getInt(9));
                // Exactly one row or the association is ambiguous.
                return r.next() ? null : placement;
            }
        } catch (Exception unavailable) {
            return null;
        }
    }
}
