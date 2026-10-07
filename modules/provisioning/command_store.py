"""Postgres store of provisioning commands (db/migrations/0015).

``accept`` writes the command, every legal entity's ERP provisioning record and the links between them in ONE
transaction the caller commits, so a command is either wholly accepted or not at all. Like the other ERP stores it never
commits.

Every committed revision of a command is announced: ``accept`` records revision 1 and ``advance`` records each later one as a
canonical ``provisioning.changed`` event in ERP's outbox, in the same transaction as the change (ADR-ERP-006). A state ERP
committed is therefore never left unannounced, and a rolled-back one is never announced."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Sequence

import psycopg

from outbox.postgres_store import PostgresOutboxStore
from provisioning import command_state
from provisioning.command_events import provisioning_changed
from provisioning.model import ErpProvisioningRequest, ProvisioningPlan
from provisioning.operation_request import ProvisioningCommand


@dataclass(frozen=True, slots=True)
class CommandRecord:
    operation_id: str
    tenant_id: str
    request_fingerprint: str
    legal_entity_ids: tuple[str, ...]
    state: str
    revision: int
    updated_at: datetime
    failure_code: str | None = None
    # The approved plan the command was accepted under (Shared erp/v1 control_plane_authority). A later read of the operation
    # must be made under a Control Plane context bound to exactly this plan.
    tenant_provisioning_id: str | None = None
    plan_id: str | None = None
    plan_version: int | None = None
    plan_digest: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedEntity:
    legal_entity_id: str
    request: ErpProvisioningRequest
    plan: ProvisioningPlan


_COLUMNS = ("operation_id, tenant_id, request_fingerprint, legal_entity_ids, state, revision, updated_at, failure_code, "
            "tenant_provisioning_id, plan_id, plan_version, plan_digest")


def _record(row) -> CommandRecord:
    return CommandRecord(operation_id=str(row[0]), tenant_id=row[1], request_fingerprint=row[2],
                         legal_entity_ids=tuple(row[3]), state=row[4], revision=row[5], updated_at=row[6],
                         failure_code=row[7], tenant_provisioning_id=row[8], plan_id=row[9], plan_version=row[10],
                         plan_digest=row[11])


class PostgresProvisioningCommandStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def lock_scope(self, tenant_id: str, idempotency_key: str) -> None:
        """Serialises concurrent commands that share an idempotency scope until the transaction ends."""
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{tenant_id}\x1f{idempotency_key}",))

    def find(self, tenant_id: str, idempotency_key: str) -> CommandRecord | None:
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT {_COLUMNS} FROM baobab.erp_provisioning_command "
                           "WHERE tenant_id = %s AND idempotency_key = %s", (tenant_id, idempotency_key))
            row = cursor.fetchone()
        return _record(row) if row else None

    def get(self, tenant_id: str, operation_id: str) -> CommandRecord | None:
        """Only a command of this tenant: another tenant's operation is absent, never forbidden."""
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT {_COLUMNS} FROM baobab.erp_provisioning_command "
                           "WHERE tenant_id = %s AND operation_id = %s", (tenant_id, operation_id))
            row = cursor.fetchone()
        return _record(row) if row else None

    def accept(self, *, command: ProvisioningCommand, idempotency_key: str, principal: str, fingerprint: str,
               entities: Sequence[PlannedEntity]) -> CommandRecord:
        operation_id = str(uuid.uuid4())
        with self._connection.cursor() as cursor:
            for entity in entities:
                cursor.execute(
                    """INSERT INTO baobab.erp_provisioning_operation
                       (provisioning_id, idempotency_key, desired_state, desired_state_digest, plan, status)
                       VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, 'planned')""",
                    (entity.request.provisioning_id, entity.request.idempotency_key,
                     json.dumps(asdict(entity.request), default=str), entity.plan.desired_state_digest,
                     json.dumps([{"key": s.key, "kind": s.kind.value, "payload": s.payload} for s in entity.plan.steps])))
            authority = command.authority
            cursor.execute(
                f"""INSERT INTO baobab.erp_provisioning_command
                    (operation_id, tenant_id, idempotency_key, principal, request_fingerprint, tenant_provisioning_id,
                     plan_id, plan_version, plan_digest, legal_entity_ids, finance_baselines)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING {_COLUMNS}""",
                (operation_id, command.tenant_id, idempotency_key, principal, fingerprint,
                 authority.tenant_provisioning_id, authority.plan_id, authority.plan_version, authority.plan_digest,
                 sorted(command.legal_entity_ids),
                 json.dumps([ref.as_contract() for ref in sorted(command.finance_baselines, key=lambda r: r.legal_entity_id)])))
            record = _record(cursor.fetchone())
            for entity in entities:
                cursor.execute(
                    "INSERT INTO baobab.erp_provisioning_command_entity (operation_id, legal_entity_id, provisioning_id) "
                    "VALUES (%s, %s, %s)", (operation_id, entity.legal_entity_id, entity.request.provisioning_id))
        self._announce(record)
        return record

    def _announce(self, record: CommandRecord) -> None:
        PostgresOutboxStore(self._connection).record_event(provisioning_changed(record))

    def advance(self, operation_id: str, state: str, failure_code: str | None = None) -> CommandRecord | None:
        """Moves a command to ``state`` as the next revision and announces it, in the caller's transaction. A state it is
        already in (with the same failure code) changes nothing and announces nothing, so a repeated projection is a no-op.
        A cancelled command stays cancelled. Returns the new record, or None when nothing changed."""
        if (state == "failed") != (failure_code is not None):
            raise ValueError("a failure code accompanies the failed state and nothing else")
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"""UPDATE baobab.erp_provisioning_command
                       SET state = %s, failure_code = %s, revision = revision + 1, updated_at = now()
                     WHERE operation_id = %s AND state <> 'cancelled'
                       AND (state <> %s OR failure_code IS DISTINCT FROM %s)
                 RETURNING {_COLUMNS}""",
                (state, failure_code, operation_id, state, failure_code))
            row = cursor.fetchone()
        if row is None:
            return None
        record = _record(row)
        self._announce(record)
        return record

    def project(self, provisioning_id: str) -> CommandRecord | None:
        """Recomputes the state of the command that owns this legal entity's provisioning record from all of its entities'
        statuses and advances the command if it changed. Called in the transaction that changed the entity's status, so the
        command, its revision and the announced event commit or roll back together. A provisioning record that belongs to no
        command is left alone."""
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT operation_id FROM baobab.erp_provisioning_command_entity WHERE provisioning_id = %s",
                           (provisioning_id,))
            owner = cursor.fetchone()
            if owner is None:
                return None
            operation_id = str(owner[0])
            # Serialise concurrent projections of one command; the row lock is held until the transaction ends.
            cursor.execute("SELECT 1 FROM baobab.erp_provisioning_command WHERE operation_id = %s FOR UPDATE", (operation_id,))
            cursor.execute(
                """SELECT o.status FROM baobab.erp_provisioning_command_entity e
                     JOIN baobab.erp_provisioning_operation o ON o.provisioning_id = e.provisioning_id
                    WHERE e.operation_id = %s""", (operation_id,))
            statuses = [row[0] for row in cursor.fetchall()]
        state, failure_code = command_state.derive(statuses)
        return self.advance(operation_id, state, failure_code)
