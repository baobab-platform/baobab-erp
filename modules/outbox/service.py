from typing import Protocol

from events.cloudevent import CloudEvent

MAX_ATTEMPTS = 8


class OutboxRecord(Protocol):
    name: str
    attempts: int
    status: str
    event: CloudEvent


class OutboxStore(Protocol):
    """Backing store for the transactional outbox (ADR-ERP-006).

    `record_event` must be called in the same database transaction as the operational
    change it describes; that atomicity guarantee lives with the caller's transaction
    boundary, not with this module.
    """

    def record_event(self, event: CloudEvent) -> None: ...

    def pending(self, limit: int = 100) -> list[OutboxRecord]: ...

    def mark_delivered(self, name: str) -> None: ...

    def mark_retry(self, name: str, attempts: int, error: str) -> None: ...

    def mark_dead_letter(self, name: str, attempts: int, error: str) -> None: ...


class EventTransport(Protocol):
    def deliver(self, event: CloudEvent) -> None: ...


def backoff_seconds(attempt: int) -> int:
    """Exponential backoff with a ceiling; jitter is the transport's responsibility."""
    return min(2**attempt, 3600)


def dispatch_pending(store: OutboxStore, transport: EventTransport) -> None:
    for record in store.pending():
        attempts = record.attempts + 1
        try:
            transport.deliver(record.event)
            store.mark_delivered(record.name)
        except Exception as exc:  # noqa: BLE001 - transport failures are expected and retried
            if attempts >= MAX_ATTEMPTS:
                store.mark_dead_letter(record.name, attempts, str(exc))
            else:
                store.mark_retry(record.name, attempts, str(exc))
