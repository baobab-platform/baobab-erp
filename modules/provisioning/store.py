import json
from typing import Any, Protocol

from provisioning.model import ProvisioningPlan, ProvisioningStatus


class ProvisioningStore(Protocol):
    def create_or_get(
        self,
        provisioning_id: str,
        idempotency_key: str,
        desired_state_digest: str,
        desired_state: dict[str, Any],
    ) -> str: ...
    def save_plan(self, plan: ProvisioningPlan) -> None: ...
    def mark_step(self, provisioning_id: str, step_key: str, status: str, result: dict[str, Any]) -> None: ...
    def completed_steps(self, provisioning_id: str) -> frozenset[str]: ...
    def set_status(self, provisioning_id: str, status: ProvisioningStatus, error: str | None = None) -> None: ...


class PostgresProvisioningStore:
    def __init__(self, connection) -> None:
        self._connection = connection

    def create_or_get(
        self,
        provisioning_id: str,
        idempotency_key: str,
        desired_state_digest: str,
        desired_state: dict[str, Any],
    ) -> str:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO baobab.erp_provisioning_operation
                   (provisioning_id, idempotency_key, desired_state_digest, desired_state, status)
                   VALUES (%s, %s, %s, %s::jsonb, 'requested')
                   ON CONFLICT (idempotency_key) DO UPDATE
                     SET updated_at = now()
                   WHERE erp_provisioning_operation.desired_state_digest = EXCLUDED.desired_state_digest
                   RETURNING provisioning_id""",
                (
                    provisioning_id,
                    idempotency_key,
                    desired_state_digest,
                    json.dumps(desired_state, default=str),
                ),
            )
            row = cursor.fetchone()
            if row is None:
                self._connection.rollback()
                raise ValueError("idempotency key was reused with different desired state")
            value = row[0]
        self._connection.commit()
        return value

    def save_plan(self, plan: ProvisioningPlan) -> None:
        payload = [{"key": step.key, "kind": step.kind.value, "payload": step.payload} for step in plan.steps]
        with self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.erp_provisioning_operation
                   SET desired_state_digest=%s, plan=%s::jsonb, status='planned', updated_at=now()
                   WHERE provisioning_id=%s""",
                (plan.desired_state_digest, json.dumps(payload), plan.provisioning_id),
            )
        self._connection.commit()

    def mark_step(self, provisioning_id: str, step_key: str, status: str, result: dict[str, Any]) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO baobab.erp_provisioning_step
                   (provisioning_id, step_key, status, result)
                   VALUES (%s, %s, %s, %s::jsonb)
                   ON CONFLICT (provisioning_id, step_key) DO UPDATE
                     SET status=EXCLUDED.status, result=EXCLUDED.result, updated_at=now()""",
                (provisioning_id, step_key, status, json.dumps(result)),
            )
        self._connection.commit()

    def completed_steps(self, provisioning_id: str) -> frozenset[str]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT step_key FROM baobab.erp_provisioning_step WHERE provisioning_id=%s AND status='completed'",
                (provisioning_id,),
            )
            return frozenset(row[0] for row in cursor.fetchall())

    def set_status(self, provisioning_id: str, status: ProvisioningStatus, error: str | None = None) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE baobab.erp_provisioning_operation
                   SET status=%s, last_error=%s, updated_at=now() WHERE provisioning_id=%s""",
                (status.value, error, provisioning_id),
            )
        self._connection.commit()
