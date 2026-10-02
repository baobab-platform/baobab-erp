"""Postgres-backed CanonicalMappingStore against baobab.entity_mapping.

See db/migrations/0003_create_entity_mapping.sql (extended by
0008_add_control_plane_mapping_context.sql: legal_entity_id, revision,
effective-dating). canonical_id is stored as a native UUID column; this class
accepts/returns it as str at the boundary, matching the rest of
modules/mapping, and casts explicitly in SQL rather than relying on implicit
driver-side UUID adaptation.
"""

import psycopg

from mapping import identifiers
from mapping.model import (
    CANONICAL_OWNERS,
    CanonicalReference,
    Mapping,
    MappingStatus,
    NativeRecordRef,
)


class PostgresCanonicalMappingStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_mapping(
        self,
        tenant_id: str,
        legal_entity_id: str,
        canonical_type: str,
        canonical_id: str,
        native_table: str,
        native_id: int,
        canonical_owner: str = "erp",
    ) -> str:
        """Persists the FIRST mapping between a canonical entity and the
        native record that represents it. This is distinct from the "lazy
        creation" ADR-ERP-007 forbids: that rule is about never fabricating a
        mapping to route around one that was expected to already exist (e.g.
        resolving a Party by matching on name because no mapping was found).
        Here the native record was just created by the same caller in the
        same operation -- recording that mapping is the mapping's legitimate
        origin, not a workaround. Must be called within the caller's own
        transaction, matching PostgresOutboxStore.record()'s convention, so
        the native record, its mapping, and its outbox event commit or roll
        back together.

        Raises psycopg.errors.UniqueViolation (uncaught) if an active mapping
        already exists for this canonical_id or this native record -- callers
        must not call this to "fix up" an existing mapping; superseding one is
        a distinct, not-yet-needed operation (see the `superseded` status and
        `replaces_mapping_id` column this table already reserves for it).
        """
        identifiers.tenant_id(tenant_id)
        identifiers.legal_entity_id(legal_entity_id)
        if canonical_owner not in CANONICAL_OWNERS:
            raise identifiers.IdentifierError(f"unknown canonical_owner {canonical_owner!r}")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.entity_mapping
                    (tenant_id, legal_entity_id, canonical_type, canonical_id,
                     native_table, native_id, canonical_owner)
                VALUES (%s, %s, %s, %s::uuid, %s, %s, %s)
                RETURNING mapping_id
                """,
                (tenant_id, legal_entity_id, canonical_type, canonical_id, native_table, native_id, canonical_owner),
            )
            return cursor.fetchone()[0]

    def get_mapping(self, tenant_id: str, mapping_id: str) -> Mapping | None:
        """The public mapping for a mapping_id, scoped to the tenant. Returns None for a mapping
        that belongs to another tenant, so a caller cannot probe across tenants."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT mapping_id, tenant_id, legal_entity_id, canonical_owner, canonical_type,
                       canonical_id::text, erp_resource_id, status, revision,
                       effective_from, effective_to,
                       (SELECT r.mapping_id FROM baobab.entity_mapping r WHERE r.id = m.replaces_mapping_id)
                FROM baobab.entity_mapping m
                WHERE m.tenant_id = %s AND m.mapping_id = %s
                """,
                (tenant_id, mapping_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        reference = (
            CanonicalReference(owner=row[3], resource_type=row[4], resource_id=row[5]) if row[3] else None
        )
        return Mapping(
            mapping_id=row[0], tenant_id=row[1], legal_entity_id=row[2], canonical_reference=reference,
            erp_resource_id=row[6], status=MappingStatus(row[7]), revision=row[8],
            effective_from=row[9], effective_to=row[10], replaces_mapping_id=row[11],
        )

    def quarantined_count(self, tenant_id: str) -> int:
        """Mappings awaiting reconciliation against Control Plane (legacy rows without a
        legal_entity_id). They are never resolved by find_native / find_canonical."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM baobab.entity_mapping WHERE tenant_id = %s AND status = 'quarantined'",
                (tenant_id,),
            )
            return cursor.fetchone()[0]

    def find_native(self, tenant_id: str, canonical_type: str, canonical_id: str) -> NativeRecordRef | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT native_table, native_id
                FROM baobab.entity_mapping
                WHERE tenant_id = %s
                  AND canonical_type = %s
                  AND canonical_id = %s::uuid
                  AND status = 'active'
                """,
                (tenant_id, canonical_type, canonical_id),
            )
            row = cursor.fetchone()
        return NativeRecordRef(table=row[0], record_id=row[1]) if row else None

    def find_canonical(self, tenant_id: str, table: str, record_id: int) -> str | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT canonical_id::text
                FROM baobab.entity_mapping
                WHERE tenant_id = %s
                  AND native_table = %s
                  AND native_id = %s
                  AND status = 'active'
                """,
                (tenant_id, table, record_id),
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def active_canonical_ids(self, tenant_id: str, canonical_type: str) -> set[str]:
        """Backs identity reconciliation (ADR-ERP-011 section 64): every canonical id
        this tenant currently has an active native mapping for, regardless of which
        native record it points at.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT canonical_id::text
                FROM baobab.entity_mapping
                WHERE tenant_id = %s
                  AND canonical_type = %s
                  AND status = 'active'
                """,
                (tenant_id, canonical_type),
            )
            return {row[0] for row in cursor.fetchall()}
