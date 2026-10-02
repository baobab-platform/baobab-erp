"""GET /inventory-availability on real Postgres mappings with a fake engine. Nothing commits; every test rolls back."""
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from application.inventory_availability import get_inventory_availability
from integration.idempiere_client import IdempiereClientError
from mapping.postgres_store import PostgresCanonicalMappingStore

# CI discovers this directory with only modules/ on the path; the fake engine lives with the unit tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from _postgres import connect  # noqa: E402
from test_inventory_availability import FakeEngine  # noqa: E402

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
PRODUCT, WAREHOUSE = 1000012, 1000003


class InventoryAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self._rollback)
        suffix = uuid.uuid4().hex[:12]
        self.tenant, self.other = f"tn_{suffix}", f"tn_{uuid.uuid4().hex[:12]}"
        self.entity, self.engine_instance = f"ZB-{suffix.upper()}", f"ei_{suffix}"
        self.sku = f"sku-{suffix}"
        self.engine = FakeEngine()
        self.requested = []
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, "
                           "legal_entity_id, engine_instance_id) VALUES (%s,%s,1001,1,%s,%s)",
                           (self.tenant, self.entity, self.entity, self.engine_instance))
            cursor.execute("INSERT INTO baobab.erp_master_data_mapping (engine_instance_id, legal_entity_id, resource_kind, "
                           "canonical_id, native_id, desired_digest, source_version) VALUES (%s,%s,'product',%s,%s,'d','1')",
                           (self.engine_instance, self.entity, self.sku, PRODUCT))
        self.warehouse_mapping = PostgresCanonicalMappingStore(self.connection).create_mapping(
            self.tenant, self.entity, "Warehouse", str(uuid.uuid4()), "M_Warehouse", WAREHOUSE)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT erp_resource_id FROM baobab.entity_mapping WHERE mapping_id = %s", (self.warehouse_mapping,))
            self.warehouse = cursor.fetchone()[0]

    def _rollback(self):
        self.connection.rollback()
        self.connection.close()

    def idempiere_for(self, ad_client_id):
        self.requested.append(ad_client_id)
        return self.engine

    def get(self, tenant=None, sku=None, warehouse=None, query=None, factory="default"):
        query = query if query is not None else f"sku_id={sku or self.sku}&warehouse_id={warehouse or self.warehouse}"
        return get_inventory_availability(
            tenant_id=tenant or self.tenant, query_string=query, connection=self.connection,
            correlation_id=str(uuid.uuid4()), trace_id=None,
            idempiere_for=self.idempiere_for if factory == "default" else factory, now=lambda: NOW)

    def test_a_mapped_sku_and_warehouse_return_the_engines_figures(self):
        status, body, headers = self.get()
        self.assertEqual((status, headers), (200, {}))
        self.assertEqual(body, {
            "legal_entity_id": self.entity, "sku_id": self.sku, "warehouse_id": self.warehouse,
            "on_hand": {"value": "42.5", "unit": "EA"}, "erp_allocated": {"value": "8", "unit": "EA"},
            "erp_available": {"value": "34.5", "unit": "EA"}, "as_of": "2026-10-02T12:00:00Z", "revision": 1790935200})
        self.assertEqual(self.requested, [1001], "the engine client is the one of the legal entity's AD_Client")

    def test_unmapped_identifiers_are_404_and_never_reach_the_engine(self):
        for case in (dict(warehouse="erp_" + uuid.uuid4().hex), dict(sku="sku-unknown"), dict(tenant=self.other)):
            with self.subTest(case):
                self.assertEqual(self.get(**case)[0], 404)
        self.assertEqual(self.requested, [])

    def test_a_product_of_another_legal_entitys_engine_instance_is_not_found(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.tenant_mapping SET engine_instance_id = NULL WHERE tenant_id = %s", (self.tenant,))
        self.assertEqual(self.get()[0], 404)

    def test_malformed_queries_are_400_with_the_offending_fields(self):
        for query in ("", f"sku_id={self.sku}", f"warehouse_id={self.warehouse}", f"sku_id=a&warehouse_id={self.warehouse}",
                      f"sku_id={self.sku}&warehouse_id=not-erp", f"sku_id={self.sku}&sku_id=x&warehouse_id={self.warehouse}",
                      f"sku_id={self.sku}&warehouse_id={self.warehouse}&extra=1", "sku_id=%20bad&warehouse_id=erp_abcd1234"):
            with self.subTest(query):
                status, body, _ = self.get(query=query)
                self.assertEqual(status, 400)
                self.assertTrue(body["errors"])
        self.assertEqual(self.requested, [])

    def test_an_unreachable_or_untrustworthy_engine_is_503_with_no_figure(self):
        self.engine.query = lambda *a, **k: (_ for _ in ()).throw(IdempiereClientError("down"))
        status, body, headers = self.get()
        self.assertEqual((status, headers.get("Retry-After")), (503, "30"))
        self.assertNotIn("on_hand", body)
        self.engine = FakeEngine()
        self.engine.records[("C_UOM", 100)] = {"id": 100}
        self.assertEqual(self.get()[0], 503)
        self.assertEqual(self.get(factory=None)[0], 503)

    def test_a_timeout_is_503_too(self):
        def slow(*a, **k):
            raise TimeoutError("timed out")
        self.engine.query = slow
        self.assertEqual(self.get()[0], 503)


if __name__ == "__main__":
    unittest.main()
