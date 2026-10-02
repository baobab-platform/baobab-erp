"""The registered ``order.consequence-changed`` event for a change of the order-consequence read model (ADR-ERP-016).

The payload is exactly the read model's contract document (``order-consequence-status.schema.json``), so the event and
``GET /order-consequences/{commerce_order_id}`` can never disagree: both are projections of one record. The event id is derived
from (tenant, order, revision), so a revision is announced once however often its transaction is retried, and
(source, id) deduplication on the consumer side holds. ERP produces this event only when the record actually changed.
"""
from __future__ import annotations

import uuid
from dataclasses import replace

from events.cloudevent import CloudEvent, new_event
from order_to_cash.consequence import OrderConsequence

EVENT_TYPE = "com.baobab-platform.erp.order.consequence-changed.v1"
_NAMESPACE = uuid.UUID("5f0cbb6e-4a0e-5a39-9d52-7a3d2d1b8c11")


def correlation_uuid(tenant_id: str, commerce_order_id: str, supplied: str | None) -> str:
    """The caller's correlation id when it is a UUID; otherwise a stable one derived from the order, so related events still
    share a correlation without inventing one per call."""
    try:
        return str(uuid.UUID(str(supplied)))
    except (ValueError, TypeError):
        return str(uuid.uuid5(_NAMESPACE, f"correlation|{tenant_id}|{commerce_order_id}"))


def consequence_changed_event(record: OrderConsequence, correlation_id: str | None) -> CloudEvent:
    event = new_event(
        type=EVENT_TYPE, subject=f"order:{record.commerce_order_id}",
        correlation_id=correlation_uuid(record.tenant_id, record.commerce_order_id, correlation_id),
        data=record.to_contract(), tenant_id=record.tenant_id, time=record.updated_at,
        idempotency_key=f"erp-order-consequence-{record.commerce_order_id}-r{record.revision}")
    event_id = str(uuid.uuid5(_NAMESPACE, f"{record.tenant_id}|{record.commerce_order_id}|{record.revision}"))
    return replace(event, id=event_id)
