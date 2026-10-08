"""The Trade customer a ``customer.projected`` event asks ERP to hold as a business partner (Shared erp/v1 customer-projection.schema.json).

Ingress verifies the signature, the registered type, producer and dataschema, and records the event. Whether the *payload* satisfies the
contract is checked again here, before anything touches the engine, because an executor must not trust that a stored row was ever
validated. A payload that does not parse is a permanent failure of that event, never guessed at. Only what ERP needs is read; a member
that is present must be well formed.

Deliberately not projected: ``tax_registration_references`` (the contract says they point at access-controlled tax identity records and
carry no raw values, so there is nothing for ERP to store) and ``billing_country`` / ``preferred_currency`` (an iDempiere business partner
has no such field of its own; they belong to its locations and price lists, which this does not create).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from mapping import identifiers

_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
CUSTOMER_TYPES = frozenset({"person", "organisation"})
STATUSES = frozenset({"active", "suspended", "closed"})
MAX_NAME = 255


class PayloadError(ValueError):
    """The event data is not a valid customer projection; carries a short, fixed reason (no payload content)."""


@dataclass(frozen=True, slots=True)
class CustomerProjection:
    legal_entity_id: str
    customer_id: str
    customer_version: int
    customer_type: str
    display_name: str
    status: str

    @property
    def active(self) -> bool:
        """Only an active customer is an active business partner; a suspended or closed one is kept (orders and history refer to it)
        but deactivated, never deleted."""
        return self.status == "active"

    def digest(self) -> str:
        """Identifies the native state this version asks for. The version is excluded: a redelivery of the same version carries the same
        digest, and a different digest under the same version is a producer error, not an update."""
        raw = json.dumps({"customer_type": self.customer_type, "display_name": self.display_name, "status": self.status},
                         sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def parse_customer_projected(data: Any) -> CustomerProjection:
    if not isinstance(data, dict):
        raise PayloadError("data is not an object")
    try:
        identifiers.legal_entity_id(data.get("legal_entity_id"))
    except identifiers.IdentifierError:
        raise PayloadError("legal_entity_id is missing or malformed") from None
    customer_id = data.get("customer_id")
    if not isinstance(customer_id, str) or not _RESOURCE_ID.fullmatch(customer_id):
        raise PayloadError("customer_id is missing or not a canonical resource id")
    version = data.get("customer_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PayloadError("customer_version must be a positive integer")
    customer_type = data.get("customer_type")
    if customer_type not in CUSTOMER_TYPES:
        raise PayloadError("customer_type must be person or organisation")
    name = data.get("display_name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or any(ord(ch) < 32 for ch in name):
        raise PayloadError("display_name must be 1-255 printable characters")
    status = data.get("status")
    if status not in STATUSES:
        raise PayloadError("status must be active, suspended or closed")
    country, currency = data.get("billing_country"), data.get("preferred_currency")
    if country is not None and (not isinstance(country, str) or not _COUNTRY.fullmatch(country)):
        raise PayloadError("billing_country must be an ISO 3166-1 alpha-2 code")
    if currency is not None and (not isinstance(currency, str) or not _CURRENCY.fullmatch(currency)):
        raise PayloadError("preferred_currency must be an ISO 4217 code")
    return CustomerProjection(data["legal_entity_id"], customer_id, version, customer_type, name.strip(), status)


MAX_MARKER = 255


def marker(tenant_id: str, customer: CustomerProjection) -> str:
    """Written into the created partner and used to find it again. Unique to this tenant, legal entity and Trade customer, so a partner
    that merely shares a name or search key can not be adopted."""
    text = f"baobab-customer:{tenant_id}:{customer.legal_entity_id}:{customer.customer_id}"
    if len(text) <= MAX_MARKER:  # the engine's Description column holds 255 characters; a longer marker would be truncated
        return text
    return "baobab-customer-sha256:" + hashlib.sha256(text.encode()).hexdigest()
