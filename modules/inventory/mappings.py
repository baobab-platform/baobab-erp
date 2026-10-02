"""Resolves the public identifiers of GET /inventory-availability to native iDempiere records, through explicit mappings only.

* the warehouse: the ERP-minted ``erp_`` identifier of an active ``M_Warehouse`` mapping of the token's tenant, which also
  names the legal entity the warehouse belongs to;
* the SKU: the Trade-owned canonical SKU id mapped to an ``M_Product`` for that legal entity's engine instance (ADR-ERP-014
  master-data mapping). The tenant's AD_Client comes from the same legal entity's active tenant mapping.

An identifier with no such mapping resolves to None; nothing is matched by name, code or position (ADR-ERP-007).
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

PRODUCT_KIND = "product"


@dataclass(frozen=True, slots=True)
class ResolvedWarehouse:
    legal_entity_id: str
    native_id: int


@dataclass(frozen=True, slots=True)
class ResolvedProduct:
    ad_client_id: int
    native_id: int


class PostgresInventoryMappings:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def warehouse(self, tenant_id: str, erp_warehouse_id: str) -> ResolvedWarehouse | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT legal_entity_id, native_id FROM baobab.entity_mapping "
                "WHERE tenant_id = %s AND erp_resource_id = %s AND native_table = 'M_Warehouse' AND status = 'active' "
                "AND legal_entity_id IS NOT NULL AND (effective_to IS NULL OR effective_to > now())",
                (tenant_id, erp_warehouse_id))
            row = cursor.fetchone()
        return ResolvedWarehouse(row[0], int(row[1])) if row else None

    def product(self, tenant_id: str, legal_entity_id: str, sku_id: str) -> ResolvedProduct | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT ad_client_id, engine_instance_id FROM baobab.tenant_mapping "
                "WHERE tenant_id = %s AND entity_id = %s AND status = 'active'", (tenant_id, legal_entity_id))
            tenant = cursor.fetchone()
            if tenant is None or tenant[1] is None:
                return None
            cursor.execute(
                "SELECT native_id FROM baobab.erp_master_data_mapping "
                "WHERE engine_instance_id = %s AND legal_entity_id = %s AND resource_kind = %s AND canonical_id = %s",
                (tenant[1], legal_entity_id, PRODUCT_KIND, sku_id))
            product = cursor.fetchone()
        return ResolvedProduct(int(tenant[0]), int(product[0])) if product else None
