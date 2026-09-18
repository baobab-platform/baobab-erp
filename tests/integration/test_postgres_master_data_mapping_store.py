import unittest
import uuid

from provisioning.master_data_mapping import PostgresMasterDataMappingStore

from _postgres import connect


class PostgresMasterDataMappingStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.engine_instance_id = f"test-engine-{uuid.uuid4()}"
        self.legal_entity_id = f"test-le-{uuid.uuid4()}"
        self.kind = "product"
        self.canonical_id = f"test-canonical-{uuid.uuid4()}"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM baobab.erp_master_data_mapping WHERE engine_instance_id = %s",
                (self.engine_instance_id,),
            )
        self.connection.commit()
        self.connection.close()

    def test_put_then_get_returns_native_id_digest_and_source_version(self):
        store = PostgresMasterDataMappingStore(self.connection)

        store.put(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id, native_id=555,
            desired_digest="digest-1", source_version="1",
        )
        result = store.get(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id,
        )

        self.assertEqual(result, (555, "digest-1", "1"))

    def test_put_is_upsert_on_the_same_canonical_identity(self):
        store = PostgresMasterDataMappingStore(self.connection)
        store.put(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id, native_id=555,
            desired_digest="digest-1", source_version="1",
        )

        store.put(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id, native_id=555,
            desired_digest="digest-2", source_version="2",
        )
        result = store.get(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id,
        )

        self.assertEqual(result, (555, "digest-2", "2"))

    def test_missing_mapping_returns_none(self):
        store = PostgresMasterDataMappingStore(self.connection)

        result = store.get(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=str(uuid.uuid4()),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
