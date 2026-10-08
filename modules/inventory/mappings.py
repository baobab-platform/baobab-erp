"""Resolves the public identifiers of GET /inventory-availability to native iDempiere records, through explicit mappings only.

* the warehouse: the ERP-minted ``erp_`` identifier of an active warehouse of the token's tenant (``baobab.erp_warehouse``: the
  identity provisioning registers, migration 0024), which also names the legal entity the warehouse belongs to;
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
            # The warehouse's native id belongs to one engine instance. It is only meaningful if that is the instance the legal entity is
            # currently provisioned onto: native ids can collide across installations, so a binding that disagrees with the active tenant
            # mapping (an engine migration in progress, a stale update) fails closed instead of reading another engine's warehouse.
            cursor.execute(
                "SELECT w.legal_entity_id, w.native_id FROM baobab.erp_warehouse w "
                "JOIN baobab.tenant_mapping tm ON tm.tenant_id = w.tenant_id AND tm.entity_id = w.legal_entity_id "
                "AND tm.status = 'active' AND tm.engine_instance_id = w.engine_instance_id "
                "WHERE w.tenant_id = %s AND w.erp_resource_id = %s AND w.status = 'active' AND w.native_id IS NOT NULL",
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
