import unittest
import uuid

from mapping.model import MappingNotFoundError, NativeRecordRef
from mapping.postgres_store import PostgresCanonicalMappingStore
from mapping.resolver import resolve_to_canonical, resolve_to_native
from reconciliation.identity import reconcile_identity

from _postgres import connect


class PostgresMappingStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.tenant_id = f"tn_{uuid.uuid4().hex[:16]}"
        self.legal_entity_id = "TEST-LE-A"
        self.canonical_id = str(uuid.uuid4())
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.entity_mapping WHERE tenant_id = %s", (self.tenant_id,))
        self.connection.commit()
        self.connection.close()

    def _insert_mapping(self, canonical_id=None, native_id=1001, canonical_type="Party"):
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.entity_mapping
                    (tenant_id, legal_entity_id, canonical_type, canonical_id, native_table, native_id)
                VALUES (%s, %s, %s, %s::uuid, %s, %s)
                """,
                (self.tenant_id, self.legal_entity_id, canonical_type, canonical_id or self.canonical_id, "C_BPartner", native_id),
            )
        self.connection.commit()

    def test_resolves_to_native_against_real_rows(self):
        self._insert_mapping()
        store = PostgresCanonicalMappingStore(self.connection)
        ref = resolve_to_native(self.tenant_id, "Party", self.canonical_id, store)
        self.assertEqual(ref, NativeRecordRef("C_BPartner", 1001))

    def test_resolves_to_canonical_against_real_rows(self):
        self._insert_mapping()
        store = PostgresCanonicalMappingStore(self.connection)
        canonical_id = resolve_to_canonical(self.tenant_id, "C_BPartner", 1001, store)
        self.assertEqual(canonical_id, self.canonical_id)

    def test_missing_mapping_raises(self):
        store = PostgresCanonicalMappingStore(self.connection)
        with self.assertRaises(MappingNotFoundError):
            resolve_to_native(self.tenant_id, "Party", str(uuid.uuid4()), store)

    def test_identity_reconciliation_against_real_rows(self):
        missing_canonical_id = str(uuid.uuid4())
        self._insert_mapping()
        store = PostgresCanonicalMappingStore(self.connection)

        result = reconcile_identity(
            self.tenant_id, "Party", {self.canonical_id, missing_canonical_id}, store
        )

        self.assertFalse(result.matches)
        self.assertEqual(result.missing, frozenset({missing_canonical_id}))
        self.assertEqual(result.unexpected, frozenset())

    def test_identity_reconciliation_flags_unexpected_mapping(self):
        self._insert_mapping()
        store = PostgresCanonicalMappingStore(self.connection)

        result = reconcile_identity(self.tenant_id, "Party", set(), store)

        self.assertFalse(result.matches)
        self.assertEqual(result.unexpected, frozenset({self.canonical_id}))


if __name__ == "__main__":
    unittest.main()


class MappingBoundaryIdentityTests(unittest.TestCase):
    """ERP-COMPAT-02: contract identifiers, five-value status, and quarantine of mappings that
    have no legal entity (never defaulted from the tenant)."""

    def setUp(self):
        self.connection = connect()
        self.tenant_id = f"tn_{uuid.uuid4().hex[:16]}"
        self.other_tenant = f"tn_{uuid.uuid4().hex[:16]}"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.connection.rollback()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM baobab.entity_mapping WHERE tenant_id = ANY(%s)",
                ([self.tenant_id, self.other_tenant],),
            )
        self.connection.commit()
        self.connection.close()

    def _create(self, tenant=None, legal_entity="TEST-LE-A", canonical_id=None, native_id=2001, owner="trade"):
        store = PostgresCanonicalMappingStore(self.connection)
        mapping_id = store.create_mapping(
            tenant or self.tenant_id, legal_entity, "customer", canonical_id or str(uuid.uuid4()),
            "C_BPartner", native_id, canonical_owner=owner,
        )
        self.connection.commit()
        return store, mapping_id

    def test_boundary_mints_contract_identifiers(self):
        store, mapping_id = self._create()
        mapping = store.get_mapping(self.tenant_id, mapping_id)
        self.assertRegex(mapping.mapping_id, r"^map_[a-z0-9]+$")
        self.assertRegex(mapping.erp_resource_id, r"^erp_[a-z0-9]+$")
        self.assertNotIn("2001", mapping.erp_resource_id)
        body = mapping.to_contract()
        self.assertEqual(body["legal_entity_id"], "TEST-LE-A")
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["revision"], 1)

    def test_one_tenant_can_map_several_legal_entities(self):
        _, first = self._create(legal_entity="TEST-LE-A", native_id=2101)
        store, second = self._create(legal_entity="TEST-LE-B", native_id=2102)
        self.assertEqual(store.get_mapping(self.tenant_id, first).legal_entity_id, "TEST-LE-A")
        self.assertEqual(store.get_mapping(self.tenant_id, second).legal_entity_id, "TEST-LE-B")

    def test_mapping_is_tenant_scoped(self):
        store, mapping_id = self._create()
        self.assertIsNone(store.get_mapping(self.other_tenant, mapping_id))

    def test_non_contract_identifiers_are_refused_before_storage(self):
        from mapping.identifiers import IdentifierError

        store = PostgresCanonicalMappingStore(self.connection)
        with self.assertRaises(IdentifierError):
            store.create_mapping("tenant-1", "TEST-LE-A", "customer", str(uuid.uuid4()), "C_BPartner", 1)
        with self.assertRaises(IdentifierError):
            store.create_mapping(self.tenant_id, "legal entity", "customer", str(uuid.uuid4()), "C_BPartner", 1)
        with self.assertRaises(IdentifierError):
            store.create_mapping(self.tenant_id, "TEST-LE-A", "customer", str(uuid.uuid4()), "C_BPartner", 1,
                                 canonical_owner="idempiere")

    def _insert_raw(self, **columns):
        names = ", ".join(columns)
        marks = ", ".join(["%s"] * len(columns))
        with self.connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO baobab.entity_mapping ({names}) VALUES ({marks})", tuple(columns.values()))

    def _raw(self, **overrides):
        base = dict(tenant_id=self.tenant_id, legal_entity_id="TEST-LE-A", canonical_type="customer",
                    canonical_id=str(uuid.uuid4()), native_table="C_BPartner", native_id=3001)
        base.update(overrides)
        return base

    def test_database_refuses_a_live_mapping_without_a_legal_entity(self):
        import psycopg

        with self.assertRaises(psycopg.errors.CheckViolation):
            self._insert_raw(**self._raw(legal_entity_id=None))

    def test_quarantined_mapping_needs_a_reason_and_never_resolves(self):
        import psycopg

        with self.assertRaises(psycopg.errors.CheckViolation):
            self._insert_raw(**self._raw(legal_entity_id=None, status="quarantined"))
        self.connection.rollback()
        canonical_id = str(uuid.uuid4())
        self._insert_raw(**self._raw(legal_entity_id=None, status="quarantined", canonical_id=canonical_id,
                                     quarantine_reason="legacy mapping has no legal_entity_id"))
        self.connection.commit()
        store = PostgresCanonicalMappingStore(self.connection)
        self.assertIsNone(store.find_native(self.tenant_id, "customer", canonical_id))
        self.assertIsNone(store.find_canonical(self.tenant_id, "C_BPartner", 3001))
        self.assertEqual(store.quarantined_count(self.tenant_id), 1)

    def test_all_five_contract_statuses_are_storable_and_superseded_is_not(self):
        import psycopg

        for index, status in enumerate(("pending", "active", "suspended", "retired")):
            self._insert_raw(**self._raw(status=status, native_id=4000 + index))
        self.connection.commit()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._insert_raw(**self._raw(status="superseded", native_id=4100))

    def test_new_rows_must_use_contract_tenant_and_legal_entity_grammar(self):
        import psycopg

        for bad in (dict(tenant_id="tenant-1"), dict(legal_entity_id="legal entity")):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=str(bad)):
                self._insert_raw(**self._raw(**bad))
            self.connection.rollback()
