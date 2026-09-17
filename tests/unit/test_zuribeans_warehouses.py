import pytest
from provisioning.warehouse import WarehouseDeclaration, validate_warehouses, WarehousePolicyError

def test_cross_legal_entity_warehouse_rejected():
    w=WarehouseDeclaration("ZB-ZA-MAIN","ZA","le-ug","m-za","ZA","org-za")
    with pytest.raises(WarehousePolicyError):
        validate_warehouses([w],legal_entity_id="le-za",market_id="m-za",country_code="ZA")
