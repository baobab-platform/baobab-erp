"""The ERP public identity of a provisioned warehouse, and the announcement of each change (db/migrations/0024).

``record`` is the one place a warehouse becomes publishable. In a single transaction it finds or mints the identity, binds it to the
approved code and the verified native record, advances the published revision when something changed, and writes the outbox row for
that revision. It is idempotent: a restart, a replayed step or a second worker leaves one identity and announces nothing twice.

Identity is found by, in order, the approved code within the legal entity and the native record within the engine instance, so it
survives a code change (the native record still binds it) and an engine migration (the code still binds it). Two different identities
claiming one code and one native record is a conflict for an operator, never resolved by picking one.
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from order_to_cash.outcome_store import PostgresDocumentOutcomeStore
from outbox.postgres_store import PostgresOutboxStore
from provisioning.warehouse_events import WarehouseIdentityConflict, warehouse_changed_event

_LOCK_SEED = 24


class PostgresWarehouseIdentityStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record(self, *, tenant_id: str, legal_entity_id: str, code: str, name: str, country: str, timezone: str | None,
               status: str, engine_instance_id: str, native_id: int, now: datetime, correlation_id: str | None = None) -> str:
        try:
            public_id = self._record(tenant_id, legal_entity_id, code, name, country, timezone, status, engine_instance_id,
                                     native_id, now, correlation_id)
            self._connection.commit()
            return public_id
        except BaseException:
            self._connection.rollback()
            raise

    def _record(self, tenant_id, legal_entity_id, code, name, country, timezone, status, engine_instance_id, native_id, now,
                correlation_id) -> str:
        with self._connection.cursor() as cursor:
            # serialise concurrent registrations of one warehouse: both look-ups below must see each other's work
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
                           (f"baobab.warehouse|{tenant_id}|{legal_entity_id}|{code}", _LOCK_SEED))
            cursor.execute("SELECT erp_resource_id FROM baobab.erp_warehouse "
                           "WHERE tenant_id = %s AND legal_entity_id = %s AND code = %s FOR UPDATE",
                           (tenant_id, legal_entity_id, code))
            by_code = cursor.fetchone()
            cursor.execute("SELECT erp_resource_id, tenant_id, legal_entity_id FROM baobab.erp_warehouse "
                           "WHERE engine_instance_id = %s AND native_id = %s FOR UPDATE", (engine_instance_id, native_id))
            by_native = cursor.fetchone()
            if by_native is not None and (by_native[1], by_native[2]) != (tenant_id, legal_entity_id):
                raise WarehouseIdentityConflict("the native record is already bound to another legal entity's warehouse")
            if by_code and by_native and by_code[0] != by_native[0]:
                raise WarehouseIdentityConflict("the approved code and the native record belong to different warehouse identities")
            found = (by_code or by_native or (None,))[0]
            if found is None:
                cursor.execute(
                    "INSERT INTO baobab.erp_warehouse (tenant_id, legal_entity_id, code, name, country, timezone, status, "
                    "engine_instance_id, native_id, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING erp_resource_id",
                    (tenant_id, legal_entity_id, code, name, country, timezone, status, engine_instance_id, native_id, now, now))
                found = cursor.fetchone()[0]
            else:  # the code, the native binding and the facts follow the approved state; the public id never changes
                cursor.execute(
                    "UPDATE baobab.erp_warehouse SET code = %s, name = %s, country = %s, timezone = %s, status = %s, "
                    "engine_instance_id = %s, native_id = %s, updated_at = %s WHERE erp_resource_id = %s",
                    (code, name, country, timezone, status, engine_instance_id, native_id, now, found))
        step = PostgresDocumentOutcomeStore(self._connection).advance(
            tenant_id=tenant_id, document_type="warehouse", document_id=found, status=status,
            detail={"code": code, "name": name, "country": country, "timezone": timezone}, now=now)
        if step.changed and timezone is not None:
            PostgresOutboxStore(self._connection).record_event(warehouse_changed_event(
                tenant_id=tenant_id, legal_entity_id=legal_entity_id, warehouse_id=found, code=code, name=name, country=country,
                timezone=timezone, status=status, revision=step.revision, now=now, correlation_id=correlation_id))
        return found
