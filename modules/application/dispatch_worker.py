"""Drains one batch of pending/retry outbox rows and attempts delivery.

Runs to completion and exits; it is meant to be invoked periodically by an
external scheduler (cron, a systemd timer, a Compose one-shot job) rather than
running its own sleep loop, so that scheduling policy stays deployment
configuration rather than code. See docs/operations.md.
"""

import os

import psycopg

from events.cloudevent import CloudEvent
from integration.delivery_transport import WebhookDestination
from integration.delivery_transport import deliver as deliver_webhook
from outbox.postgres_store import PostgresOutboxStore
from outbox.service import dispatch_pending


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


def main() -> None:
    database_url = _require_env("DATABASE_URL")
    destination = WebhookDestination(
        url=_require_env("BAOBAB_WEBHOOK_URL"),
        signing_secret=_require_env("BAOBAB_EVENT_SIGNING_SECRET"),
    )
    with psycopg.connect(database_url) as connection:
        store = PostgresOutboxStore(connection)
        dispatch_pending(store, WebhookEventTransport(destination))


if __name__ == "__main__":
    main()
