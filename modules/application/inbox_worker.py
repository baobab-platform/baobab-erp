"""Executes received ``trade.order.placed`` events: claims due inbox rows and runs each to an outcome (ADR-ERP-006, ADR-ERP-016).

Like ``dispatch_worker`` it runs to completion and exits; an external scheduler (the ``baobab-inbox-worker`` Compose loop, cron, a
systemd timer) decides how often, so scheduling stays deployment configuration. HTTP ingress stays responsible for signature,
type, producer and dataschema validation and for durable receipt; this process never serves requests. Any number of workers may
run at once: rows are claimed with ``FOR UPDATE SKIP LOCKED`` under a lease, and an order is executed under a per-order advisory
lock, so no order gets two sales orders (see ``order_to_cash.inbox_execution``).

Configuration:
* ``DATABASE_URL`` (required; a direct connection, not a transaction-mode pooler, because the per-order lock is session-level);
* ``IDEMPIERE_CLIENT_CREDENTIALS_JSON``, the same per-AD_Client credentials the HTTP application reads. A tenant whose AD_Client
  has none is *blocked* (retried slowly), not failed;
* ``BAOBAB_INBOX_BATCH_LIMIT`` (default 50 rows per run) and ``BAOBAB_INBOX_LEASE_SECONDS`` (default 300; it must exceed the
  longest time one order can spend in the engine, because an expired lease lets another worker take the row).

One JSON line is written per run: what this pass did, and the backlog by status afterwards, so an alert can watch ``blocked``,
``dead_letter`` and the age of ``received``.
"""
from __future__ import annotations

import json
import os
import socket
import sys

import psycopg

from inbox.postgres_queue import PostgresInboxQueue
from integration.idempiere_client import RestIdempiereClient
from order_to_cash.inbox_execution import ORDER_PLACED, run_claim


def _engine_factory(credentials: dict):
    def engine_for(ad_client_id: int):
        found = credentials.get(ad_client_id)
        return RestIdempiereClient(found) if found is not None else None

    return engine_for


def run_once(connection: psycopg.Connection, engine_for, *, worker_id: str, limit: int = 50, lease_seconds: int = 300) -> dict:
    queue = PostgresInboxQueue(connection)
    done: dict[str, int] = {}
    codes: dict[str, int] = {}
    for _ in range(limit):
        claim = queue.claim(event_type=ORDER_PLACED, worker_id=worker_id, lease_seconds=lease_seconds)
        if claim is None:
            break
        outcome = run_claim(claim, connection, queue, engine_for)
        done[outcome.status] = done.get(outcome.status, 0) + 1
        codes[outcome.code] = codes.get(outcome.code, 0) + 1
    return {"event": "inbox.execute", "event_type": ORDER_PLACED, "worker": worker_id, "pass": done, "codes": codes,
            "backlog": queue.counts(ORDER_PLACED)}


def main() -> None:
    from application.server import _load_idempiere_credentials  # the HTTP application's own parsing, not a copy

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    limit = int(os.environ.get("BAOBAB_INBOX_BATCH_LIMIT", "50"))
    lease = int(os.environ.get("BAOBAB_INBOX_LEASE_SECONDS", "300"))
    if limit < 1 or lease < 30:
        raise RuntimeError("BAOBAB_INBOX_BATCH_LIMIT must be >= 1 and BAOBAB_INBOX_LEASE_SECONDS >= 30")
    engine_for = _engine_factory(_load_idempiere_credentials())
    with psycopg.connect(database_url) as connection:
        report = run_once(connection, engine_for, worker_id=f"{socket.gethostname()}-{os.getpid()}", limit=limit,
                          lease_seconds=lease)
    print(json.dumps(report, sort_keys=True), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()
