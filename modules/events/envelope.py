from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """LEGACY internal event shape (pre-CloudEvents, ADR-ERP-006 as first written).

    Shared archives this shape as rejected for cross-engine delivery
    (contracts/events/v1/compatibility/legacy-trade-erp-event.json). It survives only as the input of ERP's own
    domain recorders (order-to-cash, /outbox/record), whose rows are stored as 'held' and never delivered.
    New code publishes events.cloudevent.CloudEvent."""

    event_id: str
    event_type: str
    schema_version: str
    occurred_at: datetime
    source: str
    correlation_id: str
    tenant_id: str
    entity_id: str
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EventEnvelope":
        required = {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
            "source",
            "correlation_id",
            "tenant_id",
            "entity_id",
            "payload",
        }
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"Missing event envelope fields: {', '.join(missing)}")
        occurred_at = datetime.fromisoformat(str(value["occurred_at"]).replace("Z", "+00:00"))
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if not isinstance(value["payload"], dict):
            raise ValueError("payload must be an object")
        return cls(occurred_at=occurred_at.astimezone(UTC), **{k: value[k] for k in required - {"occurred_at"}})
