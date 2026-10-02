from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class NativeRecordRef:
    """A pointer to one iDempiere native record. Never used as a cross-engine identifier."""

    table: str
    record_id: int


class MappingNotFoundError(Exception):
    """Raised when no active Mapping/ExternalReference exists for a canonical identity.

    Per ADR-ERP-007, a missing mapping is a business exception; callers must not
    fall back to matching by display name or lazily creating a native record.
    """


class MappingStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"
    QUARANTINED = "quarantined"


CANONICAL_OWNERS = frozenset(
    {"control-plane", "shared", "trade", "erp", "identity-provider", "payment-provider"}
)


@dataclass(frozen=True, slots=True)
class CanonicalReference:
    owner: str
    resource_type: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class Mapping:
    """One canonical-to-ERP mapping as contracts/erp/v1/mapping.schema.json describes it.

    The native iDempiere pointer is deliberately absent: vendor bindings stay private to the
    adapter and never appear in a public mapping.
    """

    mapping_id: str
    tenant_id: str
    legal_entity_id: str | None
    canonical_reference: CanonicalReference | None
    erp_resource_id: str
    status: MappingStatus
    revision: int
    effective_from: datetime
    effective_to: datetime | None = None
    replaces_mapping_id: str | None = None

    def to_contract(self) -> dict:
        """The public representation. Only a live (non-quarantined) mapping with a legal entity
        and a canonical owner is a valid contract document; anything else is an error here
        rather than a silently incomplete payload."""
        if self.legal_entity_id is None or self.canonical_reference is None:
            raise ValueError(
                f"mapping {self.mapping_id} lacks legal_entity_id or canonical owner "
                f"(status {self.status.value}); it is not publishable until reconciled"
            )
        body = {
            "mapping_id": self.mapping_id,
            "tenant_id": self.tenant_id,
            "legal_entity_id": self.legal_entity_id,
            "canonical_reference": {
                "owner": self.canonical_reference.owner,
                "resource_type": self.canonical_reference.resource_type,
                "resource_id": self.canonical_reference.resource_id,
            },
            "erp_resource_id": self.erp_resource_id,
            "status": self.status.value,
            "revision": self.revision,
            "effective_from": self.effective_from.isoformat(),
        }
        if self.effective_to is not None:
            body["effective_to"] = self.effective_to.isoformat()
        if self.replaces_mapping_id is not None:
            body["replaces_mapping_id"] = self.replaces_mapping_id
        return body
