"""``com.baobab-platform.erp.provisioning.changed.v1``: the canonical event for one committed revision of a provisioning
command (Shared erp/v1 AsyncAPI 1.1.0, docs/architecture/signed-event-delivery.md).

The event's identity is a function of the change, never of the delivery: ``id`` is the version 5 UUID (URL namespace) of
``urn:baobab-platform:event:erp-provisioning:{operation_id}:{revision}`` and the idempotency key is
``erp-provisioning-{operation_id}-r{revision}``. Rebuilding the event for a revision, re-recording it, or delivering it again
therefore produces the same event, and a consumer deduplicates by (source, id). The correlation id is likewise derived from the
operation, and ``time`` is the row's own ``updated_at``, so the same revision always serialises to the same bytes.

The data is exactly what ``GET /provisioning-operations/{operation_id}`` answers, so an event and the read it triggers agree. It
is a trigger to inspect authoritative state, not the state. Nothing here knows how the event is delivered.
"""
from __future__ import annotations

import uuid
from datetime import timezone
from typing import Any, Protocol

from events import registry
from events.cloudevent import CloudEvent

EVENT_TYPE = "com.baobab-platform.erp.provisioning.changed.v1"


class _Command(Protocol):
    operation_id: str
    tenant_id: str
    legal_entity_ids: Any
    state: str
    revision: int
    updated_at: Any
    failure_code: str | None


def state_document(record: _Command) -> dict:
    """erp/v1 ProvisioningState: the body of the operation read and the data of the event."""
    body = {"operation_id": record.operation_id, "tenant_id": record.tenant_id,
            "legal_entity_ids": sorted(record.legal_entity_ids), "state": record.state, "revision": record.revision,
            "updated_at": record.updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
    if record.failure_code:
        body["failure_code"] = record.failure_code
    return body


def event_id(operation_id: str, revision: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:baobab-platform:event:erp-provisioning:{operation_id}:{revision}"))


def idempotency_key(operation_id: str, revision: int) -> str:
    return f"erp-provisioning-{operation_id}-r{revision}"


def correlation_id(operation_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:baobab-platform:correlation:erp-provisioning:{operation_id}"))


def provisioning_changed(record: _Command) -> CloudEvent:
    return CloudEvent(
        id=event_id(record.operation_id, record.revision), type=EVENT_TYPE, source=registry.ERP_SOURCE,
        subject=f"provisioning:{record.operation_id}", time=record.updated_at.astimezone(timezone.utc),
        dataschema=registry.dataschema_for(EVENT_TYPE), baobabscope="tenant",
        correlationid=correlation_id(record.operation_id), data=state_document(record), tenantid=record.tenant_id,
        idempotencykey=idempotency_key(record.operation_id, record.revision)).validate()
