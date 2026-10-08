"""``erp.warehouse.changed.v1``: the ERP warehouse a legal entity's approved configuration provisioned (Shared erp/v1 warehouse-projection).

Built only from what ERP applied: the approved code, the name written to the engine, the market's country and the warehouse's declared
timezone (ERP deployment configuration; never derived from the country). ``warehouse_id`` is the ERP public id, never the iDempiere
record id. A warehouse without a declared timezone (a request accepted before the input existed) is registered but not announced:
the contract requires the member and ERP does not invent it.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime

from events.cloudevent import CloudEvent, new_event

class WarehouseIdentityConflict(Exception):
    """The approved code and the native record already belong to different ERP warehouse identities."""


EVENT = "com.baobab-platform.erp.warehouse.changed.v1"
_NAMESPACE = uuid.UUID("0a6e1d52-8f4b-5e07-9c1a-7b3d2e9f4a62")


def warehouse_changed_event(*, tenant_id: str, legal_entity_id: str, warehouse_id: str, code: str, name: str, country: str,
                            timezone: str, status: str, revision: int, now: datetime, correlation_id: str | None) -> CloudEvent:
    data = {"legal_entity_id": legal_entity_id, "warehouse_id": warehouse_id, "code": code, "name": name, "country": country,
            "timezone": timezone, "status": status, "revision": revision}
    try:
        correlation = str(uuid.UUID(str(correlation_id)))
    except (ValueError, TypeError):
        correlation = str(uuid.uuid5(_NAMESPACE, f"correlation|{tenant_id}|{warehouse_id}"))
    event = new_event(type=EVENT, subject=f"warehouse:{warehouse_id}", correlation_id=correlation, data=data, tenant_id=tenant_id,
                      time=now, idempotency_key=f"erp-warehouse-{warehouse_id}-r{revision}")
    return replace(event, id=str(uuid.uuid5(_NAMESPACE, f"warehouse|{tenant_id}|{warehouse_id}|{revision}")))
