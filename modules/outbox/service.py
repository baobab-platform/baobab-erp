from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from events.cloudevent import CloudEvent

MAX_ATTEMPTS = 8
BACKOFF_CEILING_SECONDS = 3600


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

    def record_event(self, event: CloudEvent) -> None:
        """Records a canonical event for delivery, in the caller's transaction."""

    def pending(self, limit: int = 100, **selection) -> list[OutboxRecord]:
        """Events due for delivery, optionally narrowed by ``types`` / ``exclude_types``."""

    def mark_delivered(self, name: str) -> None:
        """The destination durably accepted the event."""

    def mark_retry(self, name: str, attempts: int, error: str, delay_seconds: int = 0) -> None:
        """Try again once ``delay_seconds`` have passed."""

    def mark_dead_letter(self, name: str, attempts: int, error: str) -> None:
        """Stop trying; the event is for an operator."""


class EventTransport(Protocol):
    def deliver(self, event: CloudEvent) -> None:
        """Delivers one event; raises on failure (PermanentDeliveryError when no retry can help)."""


class PermanentDeliveryError(Exception):
    """The destination refused the event in a way no retry can change (a malformed, conflicting, oversized or unacceptable
    event). It is dead-lettered at once for an operator, never retried."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """When delivery stops being retried. ``max_attempts`` caps the number of tries and ``horizon`` caps the time since the
    event was first recorded; whichever is set and reached first dead-letters the event. The default is the original
    attempt-count policy. A retry that only becomes due after the horizon is dead-lettered without another attempt; an event
    that was never attempted always gets its first. Signed delivery to the Control Plane is time-bound instead (Shared signed-delivery.schema.json:
    a sender stops within 72 hours, inside the receiver's seven day receipt retention) so an outage of any length under the
    horizon is ridden out rather than exhausting a small attempt count in minutes."""
    max_attempts: int | None = MAX_ATTEMPTS
    horizon: timedelta | None = None


@dataclass(frozen=True, slots=True)
class DispatchSummary:
    delivered: int = 0
    retried: int = 0
    dead_lettered: int = 0


def backoff_seconds(attempt: int) -> int:
    """Exponential backoff with a ceiling; jitter is the transport's responsibility."""
    return min(2**attempt, BACKOFF_CEILING_SECONDS)


def dispatch_pending(store: OutboxStore, transport: EventTransport, policy: RetryPolicy = RetryPolicy(), *,
                     limit: int = 100, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                     **selection) -> DispatchSummary:
    delivered = retried = dead_lettered = 0
    for record in store.pending(limit, **selection):
        attempts = record.attempts + 1
        created_at = getattr(record, "created_at", None)
        if (policy.horizon is not None and record.attempts > 0 and created_at is not None
                and now() - created_at >= policy.horizon):
            # A retry that only became due after the horizon is not attempted: the sender has already stopped.
            store.mark_dead_letter(record.name, record.attempts, "the retry horizon elapsed before the next attempt")
            dead_lettered += 1
            continue
        try:
            transport.deliver(record.event)
            store.mark_delivered(record.name)
            delivered += 1
        except PermanentDeliveryError as exc:
            store.mark_dead_letter(record.name, attempts, str(exc))
            dead_lettered += 1
        except Exception as exc:  # noqa: BLE001 - transport failures are expected and retried
            exhausted = (policy.max_attempts is not None and attempts >= policy.max_attempts) or (
                policy.horizon is not None and created_at is not None and now() - created_at >= policy.horizon)
            if exhausted:
                store.mark_dead_letter(record.name, attempts, str(exc))
                dead_lettered += 1
            else:
                store.mark_retry(record.name, attempts, str(exc), backoff_seconds(attempts))
                retried += 1
    return DispatchSummary(delivered, retried, dead_lettered)
