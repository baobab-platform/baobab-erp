"""Seam for Control Plane-authoritative (tenant, legal entity) context.

ERP does not discover a legal entity from a tenant: a tenant may have several, via explicit
TenantLegalEntityMapping (ADR-BCP-018). The legal entity arrives in a CP-issued
provisioning request or resolved context and ERP validates and persists it.

Sources of legal_entity_id, in order of authority:
  provisioning request legal_entity_ids[]  ->  the specific entity being provisioned
  trusted resolved context                 ->  runtime requests
  governed event payload                   ->  where the contract requires it
Never: manual input, tenant or organisation names, inference from the ERP database, or the
Shared registry (reference only, not runtime authority).
"""

from dataclasses import dataclass
from typing import Protocol

from mapping import identifiers


@dataclass(frozen=True, slots=True)
class LegalEntityContext:
    tenant_id: str
    legal_entity_id: str

    def __post_init__(self) -> None:
        identifiers.tenant_id(self.tenant_id)
        identifiers.legal_entity_id(self.legal_entity_id)


class ControlPlaneContextPort(Protocol):
    """Validate an explicit (tenant, legal entity) pair against Control Plane authority.

    The port intentionally has no lookup-by-tenant method. A workload-facing implementation
    needs a narrow canonical relation contract from Control Plane; it must not reuse the
    administrative tenant API or read the Control Plane database.
    """

    def validate_context(self, tenant_id: str, legal_entity_id: str) -> LegalEntityContext: ...
