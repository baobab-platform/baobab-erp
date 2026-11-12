import random
import unittest
import uuid

from context.model import ContextResolutionError
from context.postgres_store import PostgresTenantMappingStore
from context.resolver import resolve_context, resolve_tenant

from _postgres import connect


class PostgresContextStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.tenant_id = f"test-tenant-{uuid.uuid4()}"
        self.entity_id = f"test-entity-{uuid.uuid4()}"
        # Randomised rather than a fixed literal: baobab.tenant_mapping now has a unique
        # index on (ad_client_id, ad_org_id) WHERE status = 'active', so a fixed value
        # could collide with another active row already present in the database.
        self.ad_client_id = random.randint(100000, 999999)
        self.ad_org_id = 1
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s", (self.tenant_id,))
        self.connection.commit()
        self.connection.close()

    def _insert_mapping(self, status="active"):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (self.tenant_id, self.entity_id, self.ad_client_id, self.ad_org_id, status),
            )
        self.connection.commit()

    def test_resolves_a_real_active_mapping(self):
        self._insert_mapping()
        store = PostgresTenantMappingStore(self.connection)
        context = resolve_context(self.tenant_id, self.entity_id, store)
        self.assertEqual((context.ad_client_id, context.ad_org_id), (self.ad_client_id, self.ad_org_id))

    def test_suspended_mapping_fails_closed(self):
        self._insert_mapping(status="suspended")
        store = PostgresTenantMappingStore(self.connection)
        with self.assertRaises(ContextResolutionError):
            resolve_context(self.tenant_id, self.entity_id, store)

    def test_unknown_pair_fails_closed(self):
        store = PostgresTenantMappingStore(self.connection)
        with self.assertRaises(ContextResolutionError):
            resolve_context(self.tenant_id, "no-such-entity", store)

    def test_resolves_tenant_from_a_real_active_mapping(self):
        self._insert_mapping()
        store = PostgresTenantMappingStore(self.connection)
        context = resolve_tenant(self.ad_client_id, self.ad_org_id, store)
        self.assertEqual((context.tenant_id, context.entity_id), (self.tenant_id, self.entity_id))

    def test_future_dated_mapping_denied_in_both_directions(self):
        from datetime import datetime, timedelta, timezone

        self._insert_mapping()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.tenant_mapping
                   SET effective_from = %s
                   WHERE tenant_id = %s AND entity_id = %s""",
                (datetime.now(timezone.utc) + timedelta(days=2),
                 self.tenant_id, self.entity_id),
            )
        self.connection.commit()
        store = PostgresTenantMappingStore(self.connection)
        with self.assertRaises(ContextResolutionError):
            resolve_context(self.tenant_id, self.entity_id, store)
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(self.ad_client_id, self.ad_org_id, store)

    def test_expired_mapping_denied_in_both_directions(self):
        from datetime import datetime, timedelta, timezone

        self._insert_mapping()
        now = datetime.now(timezone.utc)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.tenant_mapping
                   SET effective_from = %s, effective_to = %s
                   WHERE tenant_id = %s AND entity_id = %s""",
                (now - timedelta(days=2), now - timedelta(days=1),
                 self.tenant_id, self.entity_id),
            )
        self.connection.commit()
        store = PostgresTenantMappingStore(self.connection)
        with self.assertRaises(ContextResolutionError):
            resolve_context(self.tenant_id, self.entity_id, store)
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(self.ad_client_id, self.ad_org_id, store)

    def test_currently_effective_bounded_mapping_resolves_both_directions(self):
        from datetime import datetime, timedelta, timezone

        self._insert_mapping()
        now = datetime.now(timezone.utc)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.tenant_mapping
                   SET effective_from = %s, effective_to = %s
                   WHERE tenant_id = %s AND entity_id = %s""",
                (now - timedelta(days=1), now + timedelta(days=1),
                 self.tenant_id, self.entity_id),
            )
        self.connection.commit()
        store = PostgresTenantMappingStore(self.connection)
        self.assertEqual(resolve_context(self.tenant_id, self.entity_id, store).ad_client_id,
                         self.ad_client_id)
        self.assertEqual(resolve_tenant(self.ad_client_id, self.ad_org_id, store).tenant_id,
                         self.tenant_id)

    def test_unknown_native_ids_fail_closed(self):
        store = PostgresTenantMappingStore(self.connection)
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(999999, 999, store)


if __name__ == "__main__":
    unittest.main()
