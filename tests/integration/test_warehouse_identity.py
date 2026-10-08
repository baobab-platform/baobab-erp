"""The ERP public identity of a warehouse (db/migrations/0024): minted once, bound to the approved code and the native record, and
announced once per change. Real Postgres; every test ends rolled back."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _postgres import connect
from provisioning.warehouse_events import WarehouseIdentityConflict
from provisioning.warehouse_identity_store import PostgresWarehouseIdentityStore

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
EVENT = "com.baobab-platform.erp.warehouse.changed.v1"
MIGRATION = Path(__file__).resolve().parents[2] / "db/migrations/0024_erp_warehouse_identity.sql"


class WarehouseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = connect()
        self.addCleanup(self.db.close)
        suffix = uuid.uuid4().hex[:12]
        self.tenant, self.entity, self.instance = f"tn_{suffix}", f"ZB-{suffix.upper()}", f"ei_{suffix}"
        self.store = PostgresWarehouseIdentityStore(_Uncommitting(self.db))

    def record(self, *, code="KLA", name=None, native=7001, timezone_="Africa/Kampala", status="active", tenant=None, entity=None,
               instance=None, at=NOW):
        return self.store.record(tenant_id=tenant or self.tenant, legal_entity_id=entity or self.entity, code=code,
                                 name=name or code, country="UG", timezone=timezone_, status=status,
                                 engine_instance_id=instance or self.instance, native_id=native, now=at)

    def events(self, tenant=None):
        with self.db.cursor() as cursor:
            cursor.execute("SELECT payload_json FROM baobab.event_outbox WHERE tenant_id = %s AND event_type = %s ORDER BY occurred_at, id",
                           (tenant or self.tenant, EVENT))
            return [row[0] for row in cursor.fetchall()]

    def test_the_identity_is_minted_once_and_a_replay_announces_nothing(self):
        first = self.record()
        again = self.record(at=NOW + timedelta(minutes=5))
        self.assertEqual(first, again)
        self.assertRegex(first, r"^erp_[a-z0-9]{4,59}$")
        [event] = self.events()
        self.assertEqual((event["warehouse_id"], event["revision"], event["timezone"], event["code"]), (first, 1, "Africa/Kampala", "KLA"))

    def test_a_changed_fact_is_the_next_revision_under_the_same_identity(self):
        first = self.record()
        self.assertEqual(self.record(name="Kampala Main", at=NOW + timedelta(hours=1)), first)
        self.assertEqual([(e["revision"], e["name"]) for e in self.events()], [(1, "KLA"), (2, "Kampala Main")])

    def test_a_code_change_keeps_the_identity_because_the_native_record_still_binds_it(self):
        first = self.record(code="KLA")
        self.assertEqual(self.record(code="KLA-MAIN", at=NOW + timedelta(hours=1)), first)
        [(count,)] = self._rows("SELECT count(*) FROM baobab.erp_warehouse WHERE tenant_id = %s", (self.tenant,))
        self.assertEqual(count, 1)
        self.assertEqual([e["code"] for e in self.events()], ["KLA", "KLA-MAIN"])

    def test_an_engine_migration_keeps_the_identity_because_the_code_still_binds_it(self):
        first = self.record(native=7001, instance=self.instance)
        self.assertEqual(self.record(native=9100, instance=self.instance + "_new", at=NOW + timedelta(hours=1)), first)
        [(instance, native)] = self._rows("SELECT engine_instance_id, native_id FROM baobab.erp_warehouse WHERE erp_resource_id = %s", (first,))
        self.assertEqual((instance, native), (self.instance + "_new", 9100))

    def test_two_identities_claiming_one_code_and_one_native_record_is_a_conflict(self):
        self.record(code="KLA", native=7001)
        self.record(code="JIN", native=7002)
        with self.assertRaises(WarehouseIdentityConflict):
            self.record(code="KLA", native=7002)  # KLA's identity, but 7002 belongs to JIN's

    def test_a_native_record_cannot_be_bound_across_legal_entities_or_tenants(self):
        self.record()
        with self.assertRaises(WarehouseIdentityConflict):
            self.record(entity=self.entity + "-X")
        with self.assertRaises(WarehouseIdentityConflict):
            self.record(tenant=self.tenant + "x")

    def test_the_same_code_in_another_tenant_is_another_identity(self):
        mine = self.record()
        other_tenant = f"tn_{uuid.uuid4().hex[:12]}"
        theirs = self.record(tenant=other_tenant, native=8001, instance=self.instance + "_other")
        self.assertNotEqual(mine, theirs)
        self.assertEqual(len(self.events(other_tenant)), 1)

    def test_a_warehouse_without_a_declared_timezone_is_registered_but_not_announced_until_it_has_one(self):
        first = self.record(timezone_=None)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.record(timezone_="Africa/Kampala", at=NOW + timedelta(hours=1)), first)
        [event] = self.events()
        self.assertEqual((event["warehouse_id"], event["timezone"]), (first, "Africa/Kampala"))

    def test_migration_carries_hand_written_warehouse_mappings_over_and_retires_the_old_row(self):
        from mapping.postgres_store import PostgresCanonicalMappingStore
        with self.db.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, legal_entity_id, "
                           "engine_instance_id) VALUES (%s,%s,1001,1,%s,%s)", (self.tenant, self.entity, self.entity, self.instance))
        mapping_id = PostgresCanonicalMappingStore(self.db).create_mapping(
            self.tenant, self.entity, "Warehouse", str(uuid.uuid4()), "M_Warehouse", 5150)
        [(public,)] = self._rows("SELECT erp_resource_id FROM baobab.entity_mapping WHERE mapping_id = %s", (mapping_id,))
        sql = MIGRATION.read_text()
        with self.db.cursor() as cursor:  # only the carry-over statements: the table already exists
            cursor.execute(sql[sql.index("INSERT INTO baobab.erp_warehouse"):])
        [(tenant, entity, instance, native, status)] = self._rows(
            "SELECT tenant_id, legal_entity_id, engine_instance_id, native_id, status FROM baobab.erp_warehouse WHERE erp_resource_id = %s",
            (public,))
        self.assertEqual((tenant, entity, instance, native, status), (self.tenant, self.entity, self.instance, 5150, "active"))
        [(old_status,)] = self._rows("SELECT status FROM baobab.entity_mapping WHERE mapping_id = %s", (mapping_id,))
        self.assertEqual(old_status, "retired")  # one live identity, not two
        # the legacy row (no code yet) adopts the approved code when provisioning registers the same native record
        self.assertEqual(self.record(code="MAIN", native=5150), public)

    def _rows(self, sql, params=()):
        with self.db.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


class _Uncommitting:
    """commit and rollback act on a savepoint, so the store's transaction boundaries are real while every test still ends rolled back."""

    def __init__(self, connection):
        self._connection = connection
        connection.execute("SAVEPOINT store")

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args, **kwargs)

    def commit(self):
        self._connection.execute("RELEASE SAVEPOINT store")
        self._connection.execute("SAVEPOINT store")

    def rollback(self):
        self._connection.execute("ROLLBACK TO SAVEPOINT store")


if __name__ == "__main__":
    unittest.main()
