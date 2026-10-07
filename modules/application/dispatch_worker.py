"""Drains one batch of due outbox rows per destination and attempts delivery.

Runs to completion and exits; it is meant to be invoked periodically by an external scheduler (cron, a systemd timer, a Compose
one-shot job) rather than running its own sleep loop, so that scheduling policy stays deployment configuration rather than
code. See docs/operations.md.

Two destinations, each carrying only what it is configured for:

* the Control Plane event ingress (``BAOBAB_CP_EVENT_INGRESS_URL``, ``BAOBAB_CP_EVENT_KEY_ID``, ``BAOBAB_CP_EVENT_SECRET_B64``):
  ``provisioning.changed`` over signed delivery (Shared signed-delivery.schema.json), retried until a 72 hour horizon;
* the legacy webhook (``BAOBAB_WEBHOOK_URL``, signed with ``BAOBAB_EVENT_SIGNING_SECRET``, which the application also uses inbound, so
  the secret alone does not enable it): every other canonical event, unchanged.

``provisioning.changed`` is never sent to the legacy webhook. A destination that is not configured is not drained, and its
events wait in the outbox (pending, not failing) until it is configured; at least one destination must be configured.
After the run one JSON line per destination reports the backlog (pending, retry, dead_letter, due, oldest undelivered age) so a
scheduler or log-based alert can act on a growing backlog or any dead letter.
"""
import json
import os
import sys
from datetime import timedelta

import psycopg

from events.cloudevent import CloudEvent
from integration.delivery_transport import WebhookDestination
from integration.delivery_transport import deliver as deliver_webhook
from integration.signed_delivery import DeliveryKey, SignedDeliveryTransport
from outbox.postgres_store import PostgresOutboxStore
from outbox.service import RetryPolicy, dispatch_pending
from provisioning.command_events import EVENT_TYPE as PROVISIONING_CHANGED

SIGNED_TYPES = (PROVISIONING_CHANGED,)
SIGNED_POLICY = RetryPolicy(max_attempts=None, horizon=timedelta(hours=72))


class WebhookEventTransport:
    def __init__(self, destination: WebhookDestination) -> None:
        self._destination = destination

    def deliver(self, event: CloudEvent) -> None:
        deliver_webhook(event, self._destination)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def _group(names: tuple[str, ...]) -> bool:
    """True when every setting of a destination is present, False when none is; a partial group is a configuration error."""
    present = [bool(os.environ.get(name)) for name in names]
    if any(present) and not all(present):
        raise RuntimeError(f"{', '.join(names)} must be set together")
    return all(present)


def _report(destination: str, summary, stats: dict) -> None:
    """One JSON line per destination. ``delivered``, ``retried`` and ``dead_lettered`` are what THIS pass did; the rest is the
    backlog afterwards (``pending``, ``retry``, ``dead_letter``, ``due``, ``oldest_undelivered_seconds``, and ``delivered_total``,
    every event ever delivered to the destination). The store's own ``delivered`` count is renamed so it can never shadow the pass's,
    and the pass counts are written last for the same reason."""
    backlog = {("delivered_total" if key == "delivered" else key): value for key, value in stats.items()}
    print(json.dumps({"event": "outbox.dispatch", "destination": destination, **backlog, "delivered": summary.delivered,
                      "retried": summary.retried, "dead_lettered": summary.dead_lettered}, sort_keys=True),
          file=sys.stdout, flush=True)


def main() -> None:
    database_url = _require_env("DATABASE_URL")
    signed = _group(("BAOBAB_CP_EVENT_INGRESS_URL", "BAOBAB_CP_EVENT_KEY_ID", "BAOBAB_CP_EVENT_SECRET_B64"))
    # BAOBAB_EVENT_SIGNING_SECRET is also the application's inbound secret and is therefore often set where no outbound webhook is
    # wanted: the legacy destination exists when its URL does, and then it needs the secret.
    legacy = bool(os.environ.get("BAOBAB_WEBHOOK_URL"))
    if legacy and not os.environ.get("BAOBAB_EVENT_SIGNING_SECRET"):
        raise RuntimeError("BAOBAB_EVENT_SIGNING_SECRET must be set with BAOBAB_WEBHOOK_URL")
    if not (signed or legacy):
        raise RuntimeError("no event destination is configured")
    with psycopg.connect(database_url) as connection:
        store = PostgresOutboxStore(connection)
        if signed:
            transport = SignedDeliveryTransport(
                url=os.environ["BAOBAB_CP_EVENT_INGRESS_URL"],
                key=DeliveryKey.from_base64(os.environ["BAOBAB_CP_EVENT_KEY_ID"], os.environ["BAOBAB_CP_EVENT_SECRET_B64"]))
            summary = dispatch_pending(store, transport, SIGNED_POLICY, types=SIGNED_TYPES)
            _report("control-plane-ingress", summary, store.stats(types=SIGNED_TYPES))
        if legacy:
            destination = WebhookDestination(url=os.environ["BAOBAB_WEBHOOK_URL"],
                                             signing_secret=os.environ["BAOBAB_EVENT_SIGNING_SECRET"])
            summary = dispatch_pending(store, WebhookEventTransport(destination), exclude_types=SIGNED_TYPES)
            _report("webhook", summary, store.stats(exclude_types=SIGNED_TYPES))


if __name__ == "__main__":
    main()
