"""What every inbox executor needs, whatever event it executes (ADR-ERP-006).

``order_to_cash.inbox_execution`` and ``customers.projection_execution`` both claim a row, find the tenant's engine placement and
master-data mappings, hold a per-key lock while the engine is touched, and settle the row as processed, retried, blocked or dead.
That machinery lives here so the two cannot drift apart; what each *does* with the event stays in its own module.

* ``Stop`` carries an ``Outcome`` out of a deep call, so a rule can end the attempt without threading return values.
* ``AdvisoryLock`` is a session-level Postgres advisory lock on one key. It survives the transaction boundaries inside an attempt and
  the database releases it if the worker's connection dies. It needs a direct (non-pooled) connection.
* ``settle`` runs one attempt and records how it ended, never raising for an event-level failure.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

import psycopg

from inbox.postgres_queue import Claim, LeaseLostError, PostgresInboxQueue
from integration.idempiere_client import IdempiereApiError, IdempiereClientError
from order_to_cash.execution_policy import Outcome, failure_outcome


class EngineOrgMismatch(Exception):
    """The engine credentials for the tenant's AD_Client are for a different AD_Org than the one its mapping names."""


class Stop(Exception):
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome


def dead(code: str, detail: str = "") -> Stop:
    return Stop(Outcome("dead_letter", code, detail))


def blocked(code: str, detail: str = "") -> Stop:
    return Stop(Outcome("blocked", code, detail))


@contextmanager
def engine_errors() -> Iterator[None]:
    """An engine call's failures as outcomes: a request the engine refuses (400/422) will be refused again, so it is a dead letter; an
    engine that is down or erroring is retried. Engine messages are never carried: they can name tenant data."""
    try:
        yield
    except IdempiereApiError as exc:
        if exc.status in (400, 422):
            raise dead("ENGINE_REJECTED", f"HTTP {exc.status}") from None
        raise Stop(Outcome("retry", "ENGINE_UNAVAILABLE", f"HTTP {exc.status}")) from None
    except IdempiereClientError:
        raise Stop(Outcome("retry", "ENGINE_UNAVAILABLE", "the engine could not be reached")) from None


@dataclass(frozen=True, slots=True)
class Target:
    ad_client_id: int
    ad_org_id: int
    engine_instance_id: str | None


class PostgresMasterData:
    """Explicit mappings only (ADR-ERP-007): a tenant's engine placement and the master-data mapping of a customer or product.
    Nothing is matched by name, code or position."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def target(self, tenant_id: str, legal_entity_id: str) -> Target | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT ad_client_id, ad_org_id, engine_instance_id FROM baobab.tenant_mapping "
                "WHERE tenant_id = %s AND entity_id = %s AND status = 'active'", (tenant_id, legal_entity_id))
            row = cursor.fetchone()
        return Target(int(row[0]), int(row[1]), row[2]) if row else None

    def native(self, engine_instance_id: str, legal_entity_id: str, kind: str, canonical_id: str) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT native_id FROM baobab.erp_master_data_mapping "
                "WHERE engine_instance_id = %s AND legal_entity_id = %s AND resource_kind = %s AND canonical_id = %s",
                (engine_instance_id, legal_entity_id, kind, canonical_id))
            row = cursor.fetchone()
        return int(row[0]) if row else None


class AdvisoryLock:
    def __init__(self, connection: psycopg.Connection, key: str) -> None:
        self._connection, self._key = connection, key
        self.held = False

    def __enter__(self) -> "AdvisoryLock":
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (self._key,))
            self.held = bool(cursor.fetchone()[0])
        self._connection.commit()
        return self

    def __exit__(self, *_exc) -> None:
        if self.held:
            self._connection.rollback()  # an aborted transaction could not run the unlock
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (self._key,))
            self._connection.commit()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def settle(claim: Claim, connection: psycopg.Connection, queue: PostgresInboxQueue, execute: Callable[[], Outcome], *,
           settled_in_attempt: frozenset[str], now: Callable[[], datetime] = utc_now) -> Outcome:
    """Runs one attempt (``execute``) for a claimed row and settles it. Never raises for an event-level failure; a lost lease or an
    unexpected error is reported as the outcome it is (a lost lease leaves the row to its new holder).

    ``settled_in_attempt`` names the processed codes whose row ``execute`` already settled inside the transaction that made them true;
    any other outcome is settled here."""
    try:
        try:
            outcome = execute()
        except Stop as stop:
            outcome = stop.outcome
        if outcome.status == "processed" and outcome.code in settled_in_attempt:
            return outcome
        outcome = failure_outcome(outcome, attempts=claim.attempts, received_at=claim.received_at, now=now())
        connection.rollback()
        if outcome.status == "processed":
            queue.processed(claim, outcome.code)
        else:
            queue.release(claim, status=outcome.status, outcome_code=outcome.code, error=outcome.detail,
                          next_attempt_at=(now() + timedelta(seconds=outcome.delay_seconds)
                                           if outcome.delay_seconds is not None else None),
                          refund_attempt=outcome.refund_attempt)
        connection.commit()
        return outcome
    except LeaseLostError:
        connection.rollback()
        return Outcome("retry", "LEASE_LOST", "another worker holds the row now")
    except Exception as exc:  # noqa: BLE001 - settle the row; the type name is the only thing recorded
        connection.rollback()
        outcome = failure_outcome(Outcome("retry", "UNEXPECTED_ERROR", type(exc).__name__), attempts=claim.attempts,
                                  received_at=claim.received_at, now=now())
        try:
            queue.release(claim, status=outcome.status, outcome_code=outcome.code, error=outcome.detail,
                          next_attempt_at=(now() + timedelta(seconds=outcome.delay_seconds)
                                           if outcome.delay_seconds is not None else None))
            connection.commit()
        except Exception:  # noqa: BLE001 - the lease will expire and the row will be re-claimed
            connection.rollback()
        return outcome
