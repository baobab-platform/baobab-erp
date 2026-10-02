"""Postgres persistence for the order-consequence read model (db/migrations/0016_order_consequence.sql).

Every write belongs to the caller's transaction (the mapping and outbox rows it relates to commit or roll back with it);
nothing here commits."""
from __future__ import annotations

from datetime import datetime

from dataclasses import dataclass

import psycopg

from order_to_cash.consequence import Fact, Facts, OrderConsequence, derive


@dataclass(frozen=True, slots=True)
class Recorded:
    """The record after a fact was noted, and whether noting it changed anything (a repeated fact changes nothing)."""

    record: OrderConsequence
    changed: bool

_FACT_COLUMN = {Fact.ORDER_COMPLETED: "order_completed_at", Fact.SHIPMENT_COMPLETED: "shipment_completed_at",
                Fact.INVOICE_POSTED: "invoice_posted_at"}
_COLUMNS = ("tenant_id, commerce_order_id, legal_entity_id, order_version, erp_order_id, status, accounting_status, "
            "inventory_status, revision, updated_at, invoice_id, exception_code")


class PostgresOrderConsequenceStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def open_order(self, *, tenant_id: str, legal_entity_id: str, commerce_order_id: str, order_version: int,
                   erp_order_id: str, now: datetime) -> OrderConsequence:
        derived = derive(Facts())
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO baobab.order_consequence (tenant_id, commerce_order_id, legal_entity_id, order_version, "
                "erp_order_id, status, accounting_status, inventory_status, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (tenant_id, commerce_order_id, legal_entity_id, order_version, erp_order_id, derived.status,
                 derived.accounting_status, derived.inventory_status, now))
        return self.get(tenant_id, commerce_order_id)

    def has_order(self, tenant_id: str, commerce_order_id: str) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM baobab.order_consequence WHERE tenant_id = %s AND commerce_order_id = %s",
                           (tenant_id, commerce_order_id))
            return cursor.fetchone() is not None

    def link_document(self, *, tenant_id: str, document_type: str, document_id: str, commerce_order_id: str) -> bool:
        """Records that a shipment or invoice belongs to an order. False (and nothing written) when ERP keeps no
        consequence record for that order."""
        if not self.has_order(tenant_id, commerce_order_id):
            return False
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO baobab.order_consequence_document (tenant_id, document_type, document_id, commerce_order_id) "
                "VALUES (%s,%s,%s,%s)", (tenant_id, document_type, document_id, commerce_order_id))
        return True

    def order_of_document(self, tenant_id: str, document_type: str, document_id: str) -> str | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT commerce_order_id FROM baobab.order_consequence_document "
                "WHERE tenant_id = %s AND document_type = %s AND document_id = %s",
                (tenant_id, document_type, document_id))
            row = cursor.fetchone()
        return row[0] if row else None

    def record_fact(self, *, tenant_id: str, commerce_order_id: str, fact: Fact, now: datetime,
                    invoice_id: str | None = None) -> Recorded | None:
        """Notes an observed fact and re-derives the status; None when ERP keeps no record for the order. Idempotent:
        a fact already recorded keeps its first timestamp, does not bump the revision and reports changed=False."""
        column = _FACT_COLUMN[fact]
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT order_completed_at, shipment_completed_at, invoice_posted_at, invoice_id "
                "FROM baobab.order_consequence WHERE tenant_id = %s AND commerce_order_id = %s FOR UPDATE",
                (tenant_id, commerce_order_id))
            row = cursor.fetchone()
            if row is None:
                return None
            already = {Fact.ORDER_COMPLETED: row[0], Fact.SHIPMENT_COMPLETED: row[1], Fact.INVOICE_POSTED: row[2]}
            changed = already[fact] is None
            if changed:
                already[fact] = now
                derived = derive(Facts(already[Fact.ORDER_COMPLETED] is not None,
                                       already[Fact.SHIPMENT_COMPLETED] is not None,
                                       already[Fact.INVOICE_POSTED] is not None))
                cursor.execute(
                    f"UPDATE baobab.order_consequence SET {column} = %s, status = %s, accounting_status = %s, "
                    "inventory_status = %s, invoice_id = COALESCE(%s, invoice_id), revision = revision + 1, "
                    "updated_at = %s WHERE tenant_id = %s AND commerce_order_id = %s",
                    (now, derived.status, derived.accounting_status, derived.inventory_status, invoice_id, now,
                     tenant_id, commerce_order_id))
        return Recorded(self.get(tenant_id, commerce_order_id), changed)

    def get(self, tenant_id: str, commerce_order_id: str) -> OrderConsequence | None:
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT {_COLUMNS} FROM baobab.order_consequence "
                           "WHERE tenant_id = %s AND commerce_order_id = %s", (tenant_id, commerce_order_id))
            row = cursor.fetchone()
        if row is None:
            return None
        return OrderConsequence(tenant_id=row[0], commerce_order_id=row[1], legal_entity_id=row[2], order_version=row[3],
                                erp_order_id=row[4], status=row[5], accounting_status=row[6], inventory_status=row[7],
                                revision=row[8], updated_at=row[9], invoice_id=row[10], exception_code=row[11])
