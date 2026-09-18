"""Data shapes for the sell-side order-to-cash command layer (ADR-ERP-016).

Money fields are always exact-decimal strings, never floats, and always paired
with an explicit currency (ADR-ERP-008 SS28-30, INV-ERP-FIN-012/013/014) --
this module never does currency-aware arithmetic itself; that's iDempiere's
job once these fields reach it via IdempiereClient.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantScope:
    """The already-resolved Baobab context a command runs under (ADR-ERP-002).
    Never construct this from caller-supplied native ids directly -- it must
    come from context.resolver.resolve_context/resolve_tenant, matching every
    other module's INV-ERP-MAP-009/010 convention of never trusting a caller-
    supplied AD_Client_ID/AD_Org_ID."""

    tenant_id: str
    legal_entity_id: str
    ad_client_id: int
    ad_org_id: int


@dataclass(frozen=True, slots=True)
class OrderLine:
    product_canonical_id: str
    quantity: str
    unit_price: str


@dataclass(frozen=True, slots=True)
class NativeDocumentRef:
    canonical_id: str
    table: str
    native_id: int


class OrderToCashError(Exception):
    """A business-rule failure specific to this module -- distinct from a raw
    IdempiereClientError (transport/API failure) or MappingNotFoundError
    (an expected-to-exist mapping is missing). Raised when a caller's request
    violates ADR-ERP-016's own invariants, e.g. asking to post an invoice that
    was never created."""
