"""Executes received Trade events: claims due inbox rows and runs each to an outcome (ADR-ERP-006, ADR-ERP-016).

Two event types are executed. ``trade.customer.projected`` is claimed first in every pass, so a customer that arrives together with its
first order is a business partner (and mapped) by the time the order is looked at; ``trade.order.placed`` follows. Each type has its own
executor and its own locks (``customers.projection_execution``, ``order_to_cash.inbox_execution``); both share ``inbox.execution_support``.

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
from typing import Callable

import psycopg

from inbox.postgres_queue import Claim, PostgresInboxQueue
from application.observability import configure, consumer_span, diagnostic_outcome
from integration.idempiere_client import RestIdempiereClient
from order_to_cash.execution_policy import ALL_ORGANIZATIONS_AD_ORG_ID, ORDER_PLACED
from customers.projection_execution import CUSTOMER_PROJECTED, run_claim as run_customer_claim
from order_to_cash.inbox_execution import EngineOrgMismatch, InboxNativeAuthority, run_claim


def _engine_factory(credentials: dict):
    def engine_for(ad_client_id: int, ad_org_id: int):
        found = credentials.get(ad_client_id)
        if found is None:
            return None
        # an engine session is bound to one AD_Org: use it only for the organisation the tenant mapping names (or, at AD_Org 0,
        # for the whole AD_Client), never silently for another legal entity's organisation
        if ad_org_id != ALL_ORGANIZATIONS_AD_ORG_ID and found.organization_id != ad_org_id:
            raise EngineOrgMismatch()
        return RestIdempiereClient(found)

    return engine_for


def run_once(connection: psycopg.Connection, engine_for, *, worker_id: str, limit: int = 50, lease_seconds: int = 300,
             authority_for: Callable[[Claim], InboxNativeAuthority | None] | None = None,
             event_types: tuple[str, ...] = (CUSTOMER_PROJECTED, ORDER_PLACED)) -> dict:
    """One pass: up to ``limit`` rows per event type, customers first. ``pass`` and ``codes`` count outcomes across both types; the
    backlog is reported per type so an alert can watch each."""
    # The DEV-11 order-only worker must not process customer projections or
    # any unqualified event type merely because it shares the same inbox.
    if event_types not in ((CUSTOMER_PROJECTED, ORDER_PLACED), (ORDER_PLACED,)):
        raise ValueError("ERP_DEV11_INBOX_EVENT_PROFILE_NOT_APPROVED")
    queue = PostgresInboxQueue(connection)
    done: dict[str, int] = {}
    codes: dict[str, int] = {}
    for event_type in event_types:
        for _ in range(limit):
            claim = queue.claim(event_type=event_type, worker_id=worker_id, lease_seconds=lease_seconds)
            if claim is None:
                break
            with consumer_span(claim.traceparent, "baobab.erp.inbox.execute") as span:
                span.set_attribute("messaging.system", "rabbitmq")
                span.set_attribute("messaging.operation.type", "process")
                span.set_attribute("baobab.erp.event_type", event_type)
                if event_type == ORDER_PLACED:
                    # Authority is re-resolved per CLAIM, never inferred from
                    # a W3C trace or a signed message's tenant field.
                    authority = None
                    if authority_for is not None:
                        try:
                            authority = authority_for(claim)
                        except Exception:
                            authority = None
                    outcome = run_claim(claim, connection, queue, engine_for, authority=authority)
                else:
                    outcome = run_customer_claim(claim, connection, queue, engine_for)
                classification = {
                    "processed": "BUSINESS_PROCESSED",
                    "blocked": "BUSINESS_BLOCKED",
                    "retry": "BUSINESS_RETRY",
                    "dead_letter": "BUSINESS_DEAD_LETTER",
                }.get(outcome.status, "BUSINESS_BLOCKED")
                diagnostic_outcome(span, classification, failed=classification != "BUSINESS_PROCESSED")
            done[outcome.status] = done.get(outcome.status, 0) + 1
            codes[outcome.code] = codes.get(outcome.code, 0) + 1
    return {"event": "inbox.execute", "worker": worker_id, "pass": done, "codes": codes,
            "backlog": queue.counts(ORDER_PLACED), "customer_backlog": queue.counts(CUSTOMER_PROJECTED)}


def main() -> None:
    from application.server import _load_idempiere_credentials  # the HTTP application's own parsing, not a copy

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    limit = int(os.environ.get("BAOBAB_INBOX_BATCH_LIMIT", "50"))
    lease = int(os.environ.get("BAOBAB_INBOX_LEASE_SECONDS", "300"))
    if limit < 1 or lease < 30:
        raise RuntimeError("BAOBAB_INBOX_BATCH_LIMIT must be >= 1 and BAOBAB_INBOX_LEASE_SECONDS >= 30")
    configure()
    # DEV-11: even disposable workers MUST never interpret an accepted
    # Trade event as native ERP posting/creation authority. This CLI is
    # stricter than the legacy directly invoked synthetic unit-test seam.
    if os.environ.get("BAOBAB_REQUIRE_LEGAL_ACTOR_GATE", "").lower() == "false":
        raise RuntimeError("ERP_INBOX_NATIVE_ACTION_GATE_CANNOT_BE_DISABLED")
    os.environ["BAOBAB_REQUIRE_LEGAL_ACTOR_GATE"] = "true"
    engine_for = _engine_factory(_load_idempiere_credentials())
    with psycopg.connect(database_url) as connection:
        # The registry is operator-owned and event-specific; the event cannot
        # name a Context, role, mandate, provider policy or authority source.
        from application.inbox_authority import from_operator_configuration
        composition = from_operator_configuration(connection, engine_for)
        profile = os.environ.get("BAOBAB_ERP_INBOX_PROFILE", "normal")
        if composition is not None and profile != "dev11-order-placed":
            raise RuntimeError("ERP_DEV11_OPERATOR_AUTHORITY_REQUIRES_ORDER_ONLY_WORKER")
        if profile not in ("normal", "dev11-order-placed"):
            raise RuntimeError("ERP_INBOX_EVENT_PROFILE_NOT_APPROVED")
        enabled_events = ((ORDER_PLACED,) if profile == "dev11-order-placed"
                          else (CUSTOMER_PROJECTED, ORDER_PLACED))
        report = run_once(connection, engine_for, worker_id=f"{socket.gethostname()}-{os.getpid()}", limit=limit,
                          lease_seconds=lease, authority_for=composition.for_claim if composition else None,
                          event_types=enabled_events)
    print(json.dumps(report, sort_keys=True), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()
