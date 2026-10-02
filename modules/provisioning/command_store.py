"""Postgres store of provisioning commands (db/migrations/0015).

``accept`` writes the command, every legal entity's ERP provisioning record and the links between them in ONE
transaction the caller commits, so a command is either wholly accepted or not at all. Like the other ERP stores it never
commits."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Sequence

import psycopg

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


@dataclass(frozen=True, slots=True)
class PlannedEntity:
    legal_entity_id: str
    request: ErpProvisioningRequest
    plan: ProvisioningPlan


_COLUMNS = "operation_id, tenant_id, request_fingerprint, legal_entity_ids, state, revision, updated_at, failure_code"


def _record(row) -> CommandRecord:
    return CommandRecord(operation_id=str(row[0]), tenant_id=row[1], request_fingerprint=row[2],
                         legal_entity_ids=tuple(row[3]), state=row[4], revision=row[5], updated_at=row[6],
                         failure_code=row[7])


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
                     plan_id, plan_version, plan_digest, legal_entity_ids)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {_COLUMNS}""",
                (operation_id, command.tenant_id, idempotency_key, principal, fingerprint,
                 authority.tenant_provisioning_id, authority.plan_id, authority.plan_version, authority.plan_digest,
                 sorted(command.legal_entity_ids)))
            record = _record(cursor.fetchone())
            for entity in entities:
                cursor.execute(
                    "INSERT INTO baobab.erp_provisioning_command_entity (operation_id, legal_entity_id, provisioning_id) "
                    "VALUES (%s, %s, %s)", (operation_id, entity.legal_entity_id, entity.request.provisioning_id))
        return record
