from __future__ import annotations
from dataclasses import dataclass
from provisioning.idempiere_adapter import ProvisioningIdempiereClient, ProvisioningMappingStore
from provisioning.warehouse import WarehouseDeclaration


@dataclass(slots=True)
class WarehouseProvisioner:
    """Not yet wired into the planner/IdempiereProvisioningAdapter step flow (that
    flow's own CREATE_WAREHOUSE handling never sets AD_Org_ID and has no per-warehouse
    legal-entity/market validation -- see this gate's conformance.yaml note). Uses a
    different resource_key scheme (warehouse:{legal_entity_id}:{code}) than
    IdempiereProvisioningAdapter._resource_key; the two paths must not both be used for
    the same warehouse until integrated, or they would create duplicate M_Warehouse
    records under different keys."""

    client: ProvisioningIdempiereClient
    mappings: ProvisioningMappingStore

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
