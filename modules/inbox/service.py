import json
from typing import Protocol

from events.cloudevent import CloudEvent, check_consumable
from security.signing import verify_signature


class InboxStore(Protocol):
    """Backing store for the idempotent event inbox (ADR-ERP-006). Deduplication is by (source, id)."""

    def exists(self, source: str, event_id: str) -> bool: ...

    def record_received(self, event: CloudEvent, data_json: str) -> None: ...


class InvalidSignatureError(Exception):
    pass


def receive(body: bytes, signature: str, secret: str, store: InboxStore) -> CloudEvent:
    """Verify, parse, deduplicate, and record an inbound canonical event. Returns the event either way.

    Anything that is not a valid, registered, correctly sourced CloudEvent is rejected with a ValueError
    (the legacy envelope included); duplicate delivery of an already-seen (source, id) is not an error:
    at-least-once delivery means callers must expect and safely ignore duplicates.
    """
    if not verify_signature(body, signature, secret):
        raise InvalidSignatureError("Invalid event signature")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("the event body is not valid JSON") from exc
    event = check_consumable(CloudEvent.from_wire(parsed))
    if store.exists(event.source, event.id):
        return event

    store.record_received(event, json.dumps(event.data, separators=(",", ":"), sort_keys=True))
    return event
