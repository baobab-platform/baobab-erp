from __future__ import annotations
from dataclasses import dataclass
from provisioning.warehouse import WarehouseDeclaration


@dataclass(slots=True)
class WarehouseProvisioner:
    client: object
    mappings: object

    def apply(self, provisioning_id: str, warehouse: WarehouseDeclaration, ad_org_id: int) -> dict:
        key=f"warehouse:{warehouse.legal_entity_id}:{warehouse.code}"
        existing=self.mappings.get_native_id(provisioning_id=provisioning_id, resource_key=key)
        if existing is not None:
            self.client.get_record("M_Warehouse", existing)
            return {"id": existing, "reused": True}
        native_id=self.client.create_record("M_Warehouse", {
            "Value": warehouse.code,
            "Name": warehouse.name,
            "AD_Org_ID": ad_org_id,
            "IsActive": warehouse.active,
        })
        self.mappings.put_native_id(provisioning_id=provisioning_id, resource_key=key, native_id=native_id)
        return {"id": native_id, "reused": False}
