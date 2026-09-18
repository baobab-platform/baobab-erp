import unittest
import uuid

from integration.trade_projection_mapping import PostgresTransactionProjectionMappingStore

from _postgres import connect


class PostgresTransactionProjectionMappingStoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.engine_instance_id = f"test-engine-{uuid.uuid4()}"
        self.legal_entity_id = f"test-le-{uuid.uuid4()}"
        self.kind = "sales_order"
        self.canonical_id = f"test-canonical-{uuid.uuid4()}"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM baobab.erp_transaction_projection_mapping WHERE engine_instance_id = %s",
                (self.engine_instance_id,),
            )
        self.connection.commit()
        self.connection.close()

    def test_put_then_get_returns_native_id_and_digest(self):
        store = PostgresTransactionProjectionMappingStore(self.connection)

        store.put(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id, native_id=777, digest="digest-1",
        )
        result = store.get(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=self.canonical_id,
        )

        self.assertEqual(result, (777, "digest-1"))

    def test_missing_mapping_returns_none(self):
        store = PostgresTransactionProjectionMappingStore(self.connection)

        result = store.get(
            engine_instance_id=self.engine_instance_id, legal_entity_id=self.legal_entity_id,
            kind=self.kind, canonical_id=str(uuid.uuid4()),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
