"""Claiming and settling received inbox rows (baobab.event_inbox, migration 0019).

``PostgresInboxStore`` records receipt; this is the work-queue side. One row is one unit of work and at most one worker holds it:

* ``claim`` takes the next due row with ``FOR UPDATE SKIP LOCKED`` and stamps a lease, in its own committed transaction, so two
  workers can never claim the same row and a worker that dies mid-row simply lets its lease expire (``status = 'processing'`` and
  ``lease_expires_at`` in the past make the row claimable again).
* ``processed`` / ``release`` are *fenced*: they only apply while the row is still ``processing`` under the same worker and the
  same attempt. A worker whose lease expired and was re-claimed finds 0 rows and gets ``LeaseLostError``; the caller must roll
  back, so its business writes disappear with it. They run in the caller's open transaction, so the outcome commits atomically
  with the business change (``processed``) and nothing here commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


class LeaseLostError(Exception):
    """The row is no longer this worker's attempt (lease expired and re-claimed, or already settled)."""


@dataclass(frozen=True, slots=True)
class Claim:
    row_id: int
    event_id: str
    event_type: str
    tenant_id: str | None
    data: dict
    attempts: int
    received_at: datetime
    correlation_id: str | None
    worker_id: str


class PostgresInboxQueue:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def claim(self, *, event_type: str, worker_id: str, lease_seconds: int) -> Claim | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE baobab.event_inbox
                   SET status = 'processing', claimed_by = %(worker)s, attempts = attempts + 1,
                       lease_expires_at = now() + make_interval(secs => %(lease)s)
                 WHERE id = (
                       SELECT id FROM baobab.event_inbox
                        WHERE envelope_format = 'cloudevents' AND event_type = %(type)s
                          AND ((status IN ('received', 'retry', 'blocked') AND next_attempt_at <= now())
                            OR (status = 'processing' AND lease_expires_at <= now()))
                        ORDER BY next_attempt_at, id
                        FOR UPDATE SKIP LOCKED LIMIT 1)
             RETURNING id, event_id::text, event_type, tenant_id, payload_json, attempts, received_at, ce_correlation_id::text
                """,
                {"worker": worker_id, "lease": lease_seconds, "type": event_type})
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            return None
        return Claim(row_id=row[0], event_id=row[1], event_type=row[2], tenant_id=row[3], data=row[4], attempts=row[5],
                     received_at=row[6], correlation_id=row[7], worker_id=worker_id)

    def processed(self, claim: Claim, outcome_code: str) -> None:
        self._settle(claim, "processed", outcome_code, None, None, refund_attempt=False)

    def release(self, claim: Claim, *, status: str, outcome_code: str, error: str, next_attempt_at: datetime | None,
                refund_attempt: bool = False) -> None:
        if status not in ("retry", "blocked", "dead_letter"):
            raise ValueError(f"not a release status: {status}")
        self._settle(claim, status, outcome_code, error[:500], next_attempt_at, refund_attempt=refund_attempt)

    def _settle(self, claim: Claim, status: str, outcome_code: str, error: str | None, next_attempt_at: datetime | None,
                *, refund_attempt: bool) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE baobab.event_inbox
                   SET status = %(status)s, outcome_code = %(code)s, last_error = %(error)s,
                       next_attempt_at = COALESCE(%(next)s, next_attempt_at),
                       attempts = attempts - %(refund)s,
                       claimed_by = NULL, lease_expires_at = NULL,
                       processed_at = CASE WHEN %(status)s = 'processed' THEN now() ELSE processed_at END
                 WHERE id = %(id)s AND status = 'processing' AND claimed_by = %(worker)s AND attempts = %(attempts)s
                """,
                {"status": status, "code": outcome_code, "error": error, "next": next_attempt_at,
                 "refund": 1 if refund_attempt else 0, "id": claim.row_id, "worker": claim.worker_id,
                 "attempts": claim.attempts})
            if cursor.rowcount != 1:
                raise LeaseLostError(f"inbox row {claim.row_id} is no longer held by {claim.worker_id}")

    def counts(self, event_type: str) -> dict[str, int]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, count(*) FROM baobab.event_inbox WHERE envelope_format = 'cloudevents' AND event_type = %s "
                "GROUP BY status", (event_type,))
            result = {status: count for status, count in cursor.fetchall()}
        self._connection.commit()
        return result
