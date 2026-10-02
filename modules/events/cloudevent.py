"""The canonical Baobab event envelope: CloudEvents 1.0 structured JSON profile
(Shared contracts/events/v1/envelope.schema.json, ADR-SHARED-008).

`validate()` enforces the envelope schema's rules in code: required members, a closed member set (so the
legacy ERP/Trade shape is rejected, not coerced), id/correlation UUIDs, the versioned type grammar, the
tenant-scope rule (a tenant event carries tenantid, a platform event must not), idempotency key, W3C trace
context. Registry membership is checked separately (events.registry) because it differs for produced and
consumed events. The pair (source, id) is the delivery deduplication key."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from mapping import identifiers

_TYPE = re.compile(r"^com\.baobab-platform\.[a-z0-9]+(?:[.-][a-z0-9]+)*\.v[1-9][0-9]*$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_TRACEPARENT = re.compile(
    r"^00-(?!00000000000000000000000000000000)[0-9a-f]{32}-(?!0000000000000000)[0-9a-f]{16}-[0-9a-f]{2}$"
)
_TRACESTATE = re.compile(r"^[ -~]+$")

REQUIRED = ("specversion", "id", "type", "source", "subject", "time", "datacontenttype", "dataschema",
            "baobabscope", "correlationid", "data")
OPTIONAL = ("causationid", "tenantid", "idempotencykey", "traceparent", "tracestate")


class EnvelopeError(ValueError):
    """The value is not a valid canonical event envelope."""


def _uuid(value: object, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise EnvelopeError(f"{name} must be a UUID") from exc


def _absolute_uri(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise EnvelopeError(f"{name} must be an absolute URI of at most {limit} characters")
    parts = urlsplit(value)
    if not parts.scheme:
        raise EnvelopeError(f"{name} must be an absolute URI")
    return value


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EnvelopeError("time must be an RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise EnvelopeError("time must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CloudEvent:
    id: str
    type: str
    source: str
    subject: str
    time: datetime
    dataschema: str
    baobabscope: str
    correlationid: str
    data: dict[str, Any]
    tenantid: str | None = None
    causationid: str | None = None
    idempotencykey: str | None = None
    traceparent: str | None = None
    tracestate: str | None = None
    specversion: str = field(default="1.0", init=False)
    datacontenttype: str = field(default="application/json", init=False)

    def validate(self) -> "CloudEvent":
        _uuid(self.id, "id")
        _uuid(self.correlationid, "correlationid")
        if self.causationid is not None:
            _uuid(self.causationid, "causationid")
        if not isinstance(self.type, str) or len(self.type) > 255 or not _TYPE.fullmatch(self.type):
            raise EnvelopeError("type must be a versioned com.baobab-platform.* event type")
        _absolute_uri(self.source, "source", 255)
        _absolute_uri(self.dataschema, "dataschema", 512)
        if not isinstance(self.subject, str) or not 1 <= len(self.subject) <= 255:
            raise EnvelopeError("subject must be 1-255 characters")
        if not isinstance(self.time, datetime) or self.time.tzinfo is None:
            raise EnvelopeError("time must be a timezone-aware datetime")
        if self.baobabscope not in ("platform", "tenant"):
            raise EnvelopeError("baobabscope must be platform or tenant")
        if self.baobabscope == "tenant":
            if self.tenantid is None:
                raise EnvelopeError("a tenant-scoped event requires tenantid")
            try:
                identifiers.tenant_id(self.tenantid)
            except identifiers.IdentifierError as exc:
                raise EnvelopeError("tenantid is not a canonical tenant identifier") from exc
        elif self.tenantid is not None:
            raise EnvelopeError("a platform-scoped event must not carry tenantid (no default tenant)")
        if self.idempotencykey is not None and not (
            16 <= len(self.idempotencykey) <= 128 and _IDEMPOTENCY.fullmatch(self.idempotencykey)
        ):
            raise EnvelopeError("idempotencykey does not match the canonical grammar")
        if self.traceparent is not None and not _TRACEPARENT.fullmatch(self.traceparent):
            raise EnvelopeError("traceparent must be a W3C trace context version 00 value")
        if self.tracestate is not None and not (
            1 <= len(self.tracestate) <= 512 and _TRACESTATE.fullmatch(self.tracestate)
        ):
            raise EnvelopeError("tracestate is not a valid W3C trace state")
        if not isinstance(self.data, dict):
            raise EnvelopeError("data must be an object")
        return self

    @property
    def dedup_key(self) -> tuple[str, str]:
        return (self.source, self.id)

    def to_wire(self) -> dict[str, Any]:
        """The structured-mode JSON document. Optional members that are absent are omitted, never null."""
        wire: dict[str, Any] = {
            "specversion": self.specversion,
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "subject": self.subject,
            "time": self.time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "datacontenttype": self.datacontenttype,
            "dataschema": self.dataschema,
            "baobabscope": self.baobabscope,
            "correlationid": self.correlationid,
            "data": self.data,
        }
        for name in OPTIONAL:
            value = getattr(self, name)
            if value is not None:
                wire[name] = value
        return wire

    @classmethod
    def from_wire(cls, value: object) -> "CloudEvent":
        if not isinstance(value, dict):
            raise EnvelopeError("an event must be a JSON object")
        unknown = sorted(set(value) - set(REQUIRED) - set(OPTIONAL))
        if unknown:
            raise EnvelopeError(f"unknown envelope members: {', '.join(unknown)}")
        missing = [name for name in REQUIRED if name not in value]
        if missing:
            raise EnvelopeError(f"missing envelope members: {', '.join(missing)}")
        if value["specversion"] != "1.0":
            raise EnvelopeError("specversion must be 1.0")
        if value["datacontenttype"] != "application/json":
            raise EnvelopeError("datacontenttype must be application/json")
        if any(value.get(name, "") is None for name in OPTIONAL):
            raise EnvelopeError("optional members must be omitted, not null")
        event = cls(
            id=value["id"], type=value["type"], source=value["source"], subject=value["subject"],
            time=_timestamp(value["time"]), dataschema=value["dataschema"], baobabscope=value["baobabscope"],
            correlationid=value["correlationid"], data=value["data"],
            **{name: value.get(name) for name in OPTIONAL},
        )
        return event.validate()


def new_event(*, type: str, subject: str, correlation_id: str, data: dict[str, Any], tenant_id: str | None,
              causation_id: str | None = None, idempotency_key: str | None = None,
              traceparent: str | None = None, time: datetime | None = None) -> CloudEvent:
    """Build an ERP-produced event for a registered type. Refuses a type ERP does not own, so no second
    vocabulary can be emitted; the dataschema is the registry's, never caller-supplied."""
    from events import registry

    if type not in registry.PRODUCED:
        raise EnvelopeError(f"{type} is not an event type baobab-erp produces")
    return CloudEvent(
        id=str(uuid.uuid4()), type=type, source=registry.ERP_SOURCE, subject=subject,
        time=(time or datetime.now(UTC)).astimezone(UTC), dataschema=registry.dataschema_for(type),
        baobabscope="tenant" if tenant_id else "platform", correlationid=correlation_id, data=data,
        tenantid=tenant_id, causationid=causation_id, idempotencykey=idempotency_key, traceparent=traceparent,
    ).validate()


def check_consumable(event: CloudEvent) -> CloudEvent:
    """An inbound event must be a registered type, carry that type's dataschema, and come from its producer."""
    from events import registry

    entry = registry.CONSUMED.get(event.type)
    if entry is None:
        raise EnvelopeError(f"{event.type} is not an event type baobab-erp consumes")
    if event.dataschema != registry.dataschema_for(event.type):
        raise EnvelopeError(f"dataschema does not match the registered schema for {event.type}")
    if event.source not in registry.accepted_sources(entry[1]):
        raise EnvelopeError(f"source is not the registered producer of {event.type}")
    if event.baobabscope != "tenant":
        raise EnvelopeError(f"{event.type} is tenant-scoped")
    return event
