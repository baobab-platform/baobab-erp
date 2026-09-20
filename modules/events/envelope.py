from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """The common signed event envelope shape for canonical Baobab events (ADR-ERP-006)."""

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
        """Accept the legacy ERP envelope and the Shared CloudEvents v1 envelope."""
        if "specversion" in value:
            mapped = {
                "event_id": value.get("id"),
                "event_type": value.get("type"),
                "schema_version": value.get("specversion"),
                "occurred_at": value.get("time"),
                "source": value.get("source"),
                "correlation_id": value.get("correlationid"),
                "tenant_id": value.get("tenantid"),
                "entity_id": value.get("entityid"),
                "payload": value.get("data"),
            }
        else:
            mapped = value

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
        missing = sorted(name for name in required if mapped.get(name) in (None, ""))
        if missing:
            raise ValueError(f"Missing event envelope fields: {', '.join(missing)}")
        occurred_at = datetime.fromisoformat(str(mapped["occurred_at"]).replace("Z", "+00:00"))
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        if not isinstance(mapped["payload"], dict):
            raise ValueError("payload must be an object")
        return cls(
            occurred_at=occurred_at.astimezone(UTC),
            **{key: mapped[key] for key in required - {"occurred_at"}},
        )
