"""HTTP helpers for Business Partner projection (ADR-ERP-022).

Kept separate from server.py so the route body is unit-testable without the
ThreadingHTTPServer handler class.
"""

from __future__ import annotations

from typing import Any

from integration.business_partner_adapter import (
    BusinessPartnerProjectionError,
    BusinessPartnerProjectionRequest,
    project_business_partner,
)
from provisioning.master_data_mapping import MasterDataMappingStore


def parse_project_request(body: dict[str, Any]) -> BusinessPartnerProjectionRequest:
    required = (
        "engine_instance_id",
        "legal_entity_id",
        "canonical_organisation_id",
        "display_name",
        "readiness_status",
        "roles",
    )
    missing = [name for name in required if name not in body]
    if missing:
        raise BusinessPartnerProjectionError(
            f"missing required fields: {', '.join(missing)}"
        )
    roles = body.get("roles")
    if not isinstance(roles, list) or not roles:
        raise BusinessPartnerProjectionError("roles must be a non-empty array")
    return BusinessPartnerProjectionRequest(
        engine_instance_id=str(body["engine_instance_id"]),
        legal_entity_id=str(body["legal_entity_id"]),
        canonical_organisation_id=str(body["canonical_organisation_id"]),
        display_name=str(body["display_name"]),
        readiness_status=body["readiness_status"],
        roles=tuple(roles),
        billing_country=body.get("billing_country"),
        default_currency=body.get("default_currency"),
        source_version=str(body.get("source_version", "1")),
        source_customer_id=body.get("source_customer_id"),
        status=body.get("status", "active"),
    )


def execute_project(
    body: dict[str, Any],
    *,
    client,
    mappings: MasterDataMappingStore,
) -> dict[str, Any]:
    """Returns the public JSON body for a successful projection."""
    request = parse_project_request(body)
    result = project_business_partner(request, client=client, mappings=mappings)
    return {
        "business_partner": result.projection.to_public_dict(),
        "created": result.created,
        "reused": result.reused,
        "updated": result.updated,
    }
