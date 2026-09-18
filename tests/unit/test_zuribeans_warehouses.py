import unittest

from provisioning.warehouse import WarehouseDeclaration, WarehousePolicyError, validate_warehouses
from provisioning.warehouse_adapter import WarehouseProvisioner


def za_warehouse(**overrides) -> WarehouseDeclaration:
    defaults = dict(
        code="ZB-ZA-MAIN", name="ZuriBeans South Africa Main Warehouse",
        legal_entity_id="le-zb-za", market_id="market-za", country_code="ZA",
        organisation_mapping_id="org-za",
    )
    defaults.update(overrides)
    return WarehouseDeclaration(**defaults)


class ValidateWarehousesTests(unittest.TestCase):
    def test_valid_warehouse_passes(self):
        result = validate_warehouses(
            [za_warehouse()], legal_entity_id="le-zb-za", market_id="market-za", country_code="ZA",
        )
        self.assertEqual(len(result), 1)

    def test_cross_legal_entity_warehouse_rejected(self):
        warehouse = za_warehouse(legal_entity_id="le-zb-ug")
        with self.assertRaises(WarehousePolicyError):
            validate_warehouses([warehouse], legal_entity_id="le-zb-za", market_id="market-za", country_code="ZA")

    def test_market_mismatch_rejected(self):
        warehouse = za_warehouse(market_id="market-ug")
        with self.assertRaises(WarehousePolicyError):
            validate_warehouses([warehouse], legal_entity_id="le-zb-za", market_id="market-za", country_code="ZA")

    def test_duplicate_warehouse_code_rejected(self):
        warehouse = za_warehouse()
        with self.assertRaises(WarehousePolicyError):
            validate_warehouses([warehouse, warehouse], legal_entity_id="le-zb-za", market_id="market-za", country_code="ZA")

    def test_missing_organisation_mapping_rejected(self):
        warehouse = za_warehouse(organisation_mapping_id="")
        with self.assertRaises(WarehousePolicyError):
            validate_warehouses([warehouse], legal_entity_id="le-zb-za", market_id="market-za", country_code="ZA")


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 100

    def create_record(self, table, fields):
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]


class FakeMappings:
    def __init__(self):
        self.values = {}

    def get_native_id(self, *, provisioning_id, resource_key):
        return self.values.get((provisioning_id, resource_key))

    def put_native_id(self, *, provisioning_id, resource_key, native_id):
        self.values[(provisioning_id, resource_key)] = native_id


class WarehouseProvisionerTests(unittest.TestCase):
    def test_apply_creates_the_warehouse_under_the_given_org(self):
        client, mappings = FakeClient(), FakeMappings()
        provisioner = WarehouseProvisioner(client=client, mappings=mappings)

        result = provisioner.apply("prov-za", za_warehouse(), ad_org_id=0)

        self.assertFalse(result["reused"])
        record = client.records[("M_Warehouse", result["id"])]
        self.assertEqual(record["AD_Org_ID"], 0)
        self.assertEqual(record["Value"], "ZB-ZA-MAIN")

    def test_apply_is_idempotent_across_retries(self):
        client, mappings = FakeClient(), FakeMappings()
        provisioner = WarehouseProvisioner(client=client, mappings=mappings)
        warehouse = za_warehouse()

        first = provisioner.apply("prov-za", warehouse, ad_org_id=0)
        second = provisioner.apply("prov-za", warehouse, ad_org_id=0)

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(client.records), 1)


if __name__ == "__main__":
    unittest.main()
