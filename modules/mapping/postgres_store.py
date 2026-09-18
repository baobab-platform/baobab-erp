"""Postgres-backed CanonicalMappingStore against baobab.entity_mapping.

See db/migrations/0003_create_entity_mapping.sql (extended by
0008_add_control_plane_mapping_context.sql: legal_entity_id, revision,
effective-dating). canonical_id is stored as a native UUID column; this class
accepts/returns it as str at the boundary, matching the rest of
modules/mapping, and casts explicitly in SQL rather than relying on implicit
driver-side UUID adaptation.
"""

import psycopg

from mapping.model import NativeRecordRef


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
    ) -> None:
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
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.entity_mapping
                    (tenant_id, legal_entity_id, canonical_type, canonical_id, native_table, native_id)
                VALUES (%s, %s, %s, %s::uuid, %s, %s)
                """,
                (tenant_id, legal_entity_id, canonical_type, canonical_id, native_table, native_id),
            )

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
