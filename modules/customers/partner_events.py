"""``erp.business-partner.changed.v1``: the ERP-owned business partner a Trade customer became (Shared erp/v1 business-partner-projection).

Produced only from what ERP did: the partner exists in the engine and has an ERP public id (``erp_``), minted by this boundary when the
mapping was first written. ``source_customer_id`` is the Trade customer id (the canonical source reference, never replaced by the public
id); the iDempiere record id is private and never appears. ``billing_country`` and ``default_currency`` are Trade's, ERP does not hold
them for the partner, so they are omitted. The role is always ``customer``: that is the only role a customer projection establishes.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime

from events.cloudevent import CloudEvent, new_event

EVENT = "com.baobab-platform.erp.business-partner.changed.v1"
_NAMESPACE = uuid.UUID("0a6e1d52-8f4b-5e07-9c1a-7b3d2e9f4a61")


def business_partner_changed_event(*, tenant_id: str, legal_entity_id: str, business_partner_id: str, source_customer_id: str,
                                   display_name: str, status: str, revision: int, now: datetime,
                                   correlation_id: str | None) -> CloudEvent:
    data = {"legal_entity_id": legal_entity_id, "business_partner_id": business_partner_id,
            "source_customer_id": source_customer_id, "roles": ["customer"], "display_name": display_name, "status": status,
            "revision": revision}
    try:
        correlation = str(uuid.UUID(str(correlation_id)))
    except (ValueError, TypeError):
        correlation = str(uuid.uuid5(_NAMESPACE, f"correlation|{tenant_id}|{business_partner_id}"))
    event = new_event(type=EVENT, subject=f"business-partner:{business_partner_id}", correlation_id=correlation, data=data,
                      tenant_id=tenant_id, time=now, idempotency_key=f"erp-business-partner-{business_partner_id}-r{revision}")
    return replace(event, id=str(uuid.uuid5(_NAMESPACE, f"business-partner|{tenant_id}|{business_partner_id}|{revision}")))
