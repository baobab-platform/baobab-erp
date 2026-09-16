"""Postgres-backed TenantMappingStore against baobab.tenant_mapping.

See db/migrations/0002_create_tenant_mapping.sql for the schema and
db/migrations/0006_add_tenant_mapping_native_unique_index.sql for the unique index
that makes find_by_native unambiguous. This class holds no connection of its own; the
caller passes a live psycopg connection so context resolution participates in
whatever transaction (if any) the caller is already in.
"""

import psycopg


class PostgresTenantMappingStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_mapping(self, tenant_id: str, entity_id: str, ad_client_id: int, ad_org_id: int) -> None:
        """Persists the tenant/legal-entity -> AD_Client/AD_Org mapping produced by
        provisioning (modules/provisioning/idempiere_adapter.py's PERSIST_MAPPING step),
        once the native AD_Client this legal entity now owns is actually configured and
        ready. Must be called within the caller's own transaction, matching
        PostgresCanonicalMappingStore.create_mapping()'s convention.

        Raises psycopg.errors.UniqueViolation (uncaught) if an active mapping already
        exists for this (tenant_id, entity_id) -- re-provisioning an existing legal
        entity is not this method's job (see the table's own `status` column for
        superseding an existing mapping, not yet needed by any caller).
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id)
                VALUES (%s, %s, %s, %s)
                """,
                (tenant_id, entity_id, ad_client_id, ad_org_id),
            )

    def find_active_mapping(self, tenant_id: str, entity_id: str) -> tuple[int, int] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ad_client_id, ad_org_id
                FROM baobab.tenant_mapping
                WHERE tenant_id = %s AND entity_id = %s AND status = 'active'
                """,
                (tenant_id, entity_id),
            )
            row = cursor.fetchone()
        return (row[0], row[1]) if row else None

    def find_by_native(self, ad_client_id: int, ad_org_id: int) -> tuple[str, str] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tenant_id, entity_id
                FROM baobab.tenant_mapping
                WHERE ad_client_id = %s AND ad_org_id = %s AND status = 'active'
                """,
                (ad_client_id, ad_org_id),
            )
            row = cursor.fetchone()
        return (row[0], row[1]) if row else None
