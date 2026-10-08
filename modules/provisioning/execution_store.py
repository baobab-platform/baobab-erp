"""Postgres side of provisioning execution: which operations are due, the per-operation lock, and how a pass is settled.

An operation is claimed by a session advisory lock on its id, held for the pass. If the worker dies, Postgres releases the lock with
its connection and the next worker resumes from the recorded steps; if it is merely slow nobody else can start the same operation.
That needs a direct Postgres connection (a transaction-mode pooler would hand the lock to another session), as the inbox worker does.
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from context.postgres_store import PostgresTenantMappingStore
from provisioning.execution import LoadedOperation, MappingConflict, Outcome, apply_budgets
from provisioning.model import ProvisioningStatus

_LOCK_SEED = 19  # keeps these locks apart from the other advisory locks taken with hashtextextended
_OPEN = ("planned", "applying", "reconciling")


class PostgresProvisioningExecutionQueue:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def due(self, limit: int) -> list[str]:
        """Operations of accepted commands that still need work and whose next attempt is due, oldest first. The operations of a
        command that has failed or been cancelled are left alone: provisioning the rest of it would only strand a half."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT o.provisioning_id
                     FROM baobab.erp_provisioning_operation o
                     JOIN baobab.erp_provisioning_command_entity e ON e.provisioning_id = o.provisioning_id
                     JOIN baobab.erp_provisioning_command c ON c.operation_id = e.operation_id
                    WHERE o.status = ANY(%s) AND c.state NOT IN ('failed', 'cancelled')
                      AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= now())
                    ORDER BY o.created_at, o.provisioning_id LIMIT %s""", (list(_OPEN), limit))
            ids = [row[0] for row in cursor.fetchall()]
        self._connection.commit()
        return ids

    def try_lock(self, provisioning_id: str) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, %s))", (provisioning_id, _LOCK_SEED))
            return bool(cursor.fetchone()[0])

    def unlock(self, provisioning_id: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, %s))", (provisioning_id, _LOCK_SEED))
        self._connection.commit()

    def begin(self, provisioning_id: str) -> LoadedOperation | None:
        """Counts this pass and returns the operation, or None if it no longer needs work (another worker finished it, or its
        command was failed or cancelled, between ``due`` and the lock)."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.erp_provisioning_operation o
                      SET attempts = attempts + 1, updated_at = now()
                    WHERE o.provisioning_id = %s AND o.status = ANY(%s)
                      AND NOT EXISTS (SELECT 1 FROM baobab.erp_provisioning_command_entity e
                                        JOIN baobab.erp_provisioning_command c ON c.operation_id = e.operation_id
                                       WHERE e.provisioning_id = o.provisioning_id AND c.state IN ('failed', 'cancelled'))
                RETURNING o.desired_state, o.desired_state_digest, o.plan, o.status, o.attempts, o.created_at""",
                (provisioning_id, list(_OPEN)))
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            return None
        state, digest, plan, status, attempts, created_at = row
        return LoadedOperation(provisioning_id, state, digest, tuple(plan or ()), status, attempts, created_at)

    def settle(self, operation: LoadedOperation, outcome: Outcome, *, store, now: datetime) -> Outcome:
        """Records how the pass ended and returns the outcome that was recorded (budgets can turn a retry into a failure). Any
        half-done transaction of the failed pass is discarded first; the steps it completed were committed one by one."""
        self._connection.rollback()
        outcome = apply_budgets(outcome, attempts=operation.attempts, created_at=operation.created_at, now=now)
        if outcome.status == "failed":
            store.set_status(operation.provisioning_id, ProvisioningStatus.FAILED, f"{outcome.code}: {outcome.detail}".rstrip(": "))
            self._record(operation.provisioning_id, outcome.code, None)
        elif outcome.status == "ready":
            self._record(operation.provisioning_id, outcome.code, None)
        else:
            # A pass that was blocked waiting for an operator did no work and spends none of the retry budget: after days of
            # waiting for a credential, the first transient engine error must not read as 24 failed attempts.
            self._record(operation.provisioning_id, outcome.code, outcome.delay_seconds or 0,
                         last_error=f"{outcome.code}: {outcome.detail}".rstrip(": "), refund=outcome.status == "blocked")
        return outcome

    def _record(self, provisioning_id: str, code: str, delay_seconds: int | None, last_error: str | None = None,
                refund: bool = False) -> None:
        # The next attempt is scheduled on the database's clock, the same one ``due`` compares it with.
        with self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.erp_provisioning_operation
                      SET outcome_code = %s,
                          next_attempt_at = CASE WHEN %s::int IS NULL THEN NULL ELSE now() + make_interval(secs => %s::int) END,
                          attempts = CASE WHEN %s THEN GREATEST(attempts - 1, 0) ELSE attempts END,
                          last_error = COALESCE(%s, last_error), updated_at = now()
                    WHERE provisioning_id = %s""", (code, delay_seconds, delay_seconds, refund, last_error, provisioning_id))
        self._connection.commit()

    def backlog(self) -> dict[str, int]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT o.status, count(*) FROM baobab.erp_provisioning_operation o
                     JOIN baobab.erp_provisioning_command_entity e ON e.provisioning_id = o.provisioning_id
                    GROUP BY o.status""")
            counts = {status: int(count) for status, count in cursor.fetchall()}
        self._connection.commit()
        return counts


class ConfirmingTenantMappings:
    """PERSIST_MAPPING's writer made repeatable. A pass that died after writing the mapping but before recording the step runs the
    step again; the same mapping is then confirmed, a different one is a conflict an operator must resolve."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._store = PostgresTenantMappingStore(connection)

    def create_mapping(self, tenant_id: str, entity_id: str, ad_client_id: int, ad_org_id: int, engine_instance_id: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT ad_client_id, ad_org_id, engine_instance_id FROM baobab.tenant_mapping
                    WHERE tenant_id = %s AND entity_id = %s AND status = 'active' FOR UPDATE""", (tenant_id, entity_id))
            existing = cursor.fetchone()
        if existing is None:
            try:
                self._store.create_mapping(tenant_id, entity_id, ad_client_id, ad_org_id, engine_instance_id)
            except psycopg.errors.UniqueViolation:  # e.g. the native AD_Client/AD_Org already maps another tenant
                raise MappingConflict("the tenant mapping collides with an existing active mapping") from None
        elif tuple(existing) != (ad_client_id, ad_org_id, engine_instance_id):
            raise MappingConflict("an active tenant mapping already names a different AD_Client, AD_Org or EngineInstance")
