import unittest

from provisioning.warehouse import WarehouseDeclaration, WarehousePolicyError, validate_warehouses


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
