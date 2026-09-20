"""ZB-04 buyer projection event consumer (ADR-ERP-023)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from events.envelope import EventEnvelope
from integration.business_partner_adapter import (
    BusinessPartnerProjectionError,
    BusinessPartnerProjectionRequest,
    BusinessPartnerProjectionResult,
    project_business_partner,
)
from provisioning.master_data_adapter import MasterDataIdempiereClient
from provisioning.master_data_mapping import MasterDataMappingStore

BUYER_PROJECTION_REQUESTED = (
    "com.baobab-platform.customer.buyer-erp-projection.requested.v1"
)


@dataclass(frozen=True, slots=True)
class BuyerProjectionCommand:
    buyer_organisation_id: str
    canonical_organisation_id: str
    display_name: str
    billing_country: str
    default_currency: str
    source_version: str

    @classmethod
    def from_envelope(cls, envelope: EventEnvelope) -> "BuyerProjectionCommand | None":
        if envelope.event_type != BUYER_PROJECTION_REQUESTED:
            return None
        payload: dict[str, Any] = envelope.payload
        required = (
            "buyer_organisation_id",
            "canonical_organisation_id",
            "display_name",
            "billing_country",
            "default_currency",
            "source_version",
        )
        missing = [name for name in required if not str(payload.get(name, "")).strip()]
        if missing:
            raise BusinessPartnerProjectionError(
                f"buyer projection event missing required fields: {', '.join(missing)}"
            )
        return cls(
            buyer_organisation_id=str(payload["buyer_organisation_id"]).strip(),
            canonical_organisation_id=str(payload["canonical_organisation_id"]).strip(),
            display_name=str(payload["display_name"]).strip(),
            billing_country=str(payload["billing_country"]).strip().upper(),
            default_currency=str(payload["default_currency"]).strip().upper(),
            source_version=str(payload["source_version"]).strip(),
        )


def consume_buyer_projection(
    envelope: EventEnvelope,
    *,
    engine_instance_id: str,
    client: MasterDataIdempiereClient,
    mappings: MasterDataMappingStore,
) -> BusinessPartnerProjectionResult | None:
    """Project an explicit legal-entity-scoped buyer command; ignore unrelated events."""
    command = BuyerProjectionCommand.from_envelope(envelope)
    if command is None:
        return None
    if not envelope.tenant_id.strip() or not envelope.entity_id.strip():
        raise BusinessPartnerProjectionError(
            "buyer projection event requires tenant_id and entity_id"
        )
    return project_business_partner(
        BusinessPartnerProjectionRequest(
            engine_instance_id=engine_instance_id,
            legal_entity_id=envelope.entity_id,
            canonical_organisation_id=command.canonical_organisation_id,
            source_customer_id=command.buyer_organisation_id,
            display_name=command.display_name,
            readiness_status="READY",
            roles=("customer",),
            billing_country=command.billing_country,
            default_currency=command.default_currency,
            source_version=command.source_version,
        ),
        client=client,
        mappings=mappings,
    )
