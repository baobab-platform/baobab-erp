"""Business Partner projection adapter (ADR-ERP-021).

Projects a readiness-gated organisation into iDempiere C_BPartner via the existing
master-data bootstrapper. Public identifiers follow Shared contracts/erp/v1
(erp_*); native C_BPartner_ID never leaves this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Sequence

from provisioning.master_data import CanonicalMasterRecord, MasterDataKind
from provisioning.master_data_adapter import IdempiereMasterDataBootstrapper, MasterDataIdempiereClient
from provisioning.master_data_mapping import MasterDataMappingStore

Role = Literal["customer", "supplier", "employee", "other"]
ReadinessStatus = Literal["NOT_REQUESTED", "READY", "PENDING", "FAILED", "PROJECTED"]
ProjectionStatus = Literal["active", "suspended", "closed"]


class BusinessPartnerProjectionError(ValueError):
    """Fail-closed validation or readiness failure for BP projection."""


@dataclass(frozen=True, slots=True)
class BusinessPartnerProjectionRequest:
    """Inbound request from estate/Trade after erp readiness is READY."""

    engine_instance_id: str
    legal_entity_id: str
    canonical_organisation_id: str
    display_name: str
    readiness_status: ReadinessStatus
    roles: Sequence[Role]
    billing_country: str | None = None
    default_currency: str | None = None
    source_version: str = "1"
    contract_version: str = "erp/v1"
    status: ProjectionStatus = "active"

    def validate(self) -> None:
        if not self.engine_instance_id.strip():
            raise BusinessPartnerProjectionError("engine_instance_id is required")
        if not self.legal_entity_id.strip():
            raise BusinessPartnerProjectionError("legal_entity_id is required")
        if not self.canonical_organisation_id.strip():
            raise BusinessPartnerProjectionError("canonical_organisation_id is required")
        if not self.display_name.strip():
            raise BusinessPartnerProjectionError("display_name is required")
        if self.readiness_status != "READY":
            raise BusinessPartnerProjectionError(
                f"readiness_status must be READY (got {self.readiness_status!r}); "
                "registration/approval is not ERP projection (ADR-0023 §10)"
            )
        if not self.roles:
            raise BusinessPartnerProjectionError("at least one role is required")
        allowed: set[str] = {"customer", "supplier", "employee", "other"}
        for role in self.roles:
            if role not in allowed:
                raise BusinessPartnerProjectionError(f"invalid role: {role!r}")
        if self.billing_country is not None and len(self.billing_country) != 2:
            raise BusinessPartnerProjectionError("billing_country must be ISO 3166-1 alpha-2")
        if self.default_currency is not None and len(self.default_currency) != 3:
            raise BusinessPartnerProjectionError("default_currency must be ISO 4217")


@dataclass(frozen=True, slots=True)
class BusinessPartnerProjection:
    """Shared contracts/erp/v1 business-partner-projection.schema.json shape."""

    legal_entity_id: str
    business_partner_id: str
    roles: tuple[Role, ...]
    display_name: str
    status: ProjectionStatus
    revision: int
    source_customer_id: str | None = None
    billing_country: str | None = None
    default_currency: str | None = None

    def to_public_dict(self) -> dict:
        body: dict = {
            "legal_entity_id": self.legal_entity_id,
            "business_partner_id": self.business_partner_id,
            "roles": list(self.roles),
            "display_name": self.display_name,
            "status": self.status,
            "revision": self.revision,
        }
        if self.source_customer_id is not None:
            body["source_customer_id"] = self.source_customer_id
        if self.billing_country is not None:
            body["billing_country"] = self.billing_country
        if self.default_currency is not None:
            body["default_currency"] = self.default_currency
        return body


@dataclass(frozen=True, slots=True)
class BusinessPartnerProjectionResult:
    projection: BusinessPartnerProjection
    created: int
    reused: int
    updated: int
    native_table: str = "C_BPartner"
    # Native id is retained only for internal mapping diagnostics — not for public APIs.
    native_record_id: int | None = None


def mint_public_business_partner_id(*, legal_entity_id: str, canonical_organisation_id: str) -> str:
    """Mint erp_* public id (Shared domain.schema.json erpResourceId)."""
    digest = sha256(f"{legal_entity_id}:{canonical_organisation_id}".encode()).hexdigest()[:24]
    return f"erp_bp{digest}"


def _to_master_record(request: BusinessPartnerProjectionRequest) -> CanonicalMasterRecord:
    is_vendor = "supplier" in request.roles
    is_customer = "customer" in request.roles
    payload: dict = {
        "Name": request.display_name.strip(),
        "IsActive": request.status == "active",
        "IsVendor": is_vendor,
        "IsCustomer": is_customer,
    }
    if request.billing_country:
        payload["C_Country_ID.CountryCode"] = request.billing_country.upper()
    return CanonicalMasterRecord(
        kind=MasterDataKind.BUSINESS_PARTNER,
        canonical_id=request.canonical_organisation_id.strip(),
        external_key=request.canonical_organisation_id.strip()[:40],
        legal_entity_id=request.legal_entity_id.strip(),
        payload=payload,
        contract_version=request.contract_version,
        source_version=request.source_version,
    )


def project_business_partner(
    request: BusinessPartnerProjectionRequest,
    *,
    client: MasterDataIdempiereClient,
    mappings: MasterDataMappingStore,
) -> BusinessPartnerProjectionResult:
    """Project a readiness-gated organisation to C_BPartner and return the public shape."""
    request.validate()
    record = _to_master_record(request)
    bootstrapper = IdempiereMasterDataBootstrapper(client=client, mappings=mappings)
    result = bootstrapper.bootstrap(
        engine_instance_id=request.engine_instance_id,
        legal_entity_id=request.legal_entity_id,
        records=[record],
    )
    if result.drift:
        raise BusinessPartnerProjectionError(
            f"business partner projection drift: {'; '.join(result.drift)}"
        )

    mapped = mappings.get(
        engine_instance_id=request.engine_instance_id,
        legal_entity_id=request.legal_entity_id,
        kind=MasterDataKind.BUSINESS_PARTNER.value,
        canonical_id=request.canonical_organisation_id.strip(),
    )
    native_id = int(mapped[0]) if mapped else None
    public_id = mint_public_business_partner_id(
        legal_entity_id=request.legal_entity_id,
        canonical_organisation_id=request.canonical_organisation_id,
    )
    revision = int(request.source_version) if request.source_version.isdigit() else 1
    projection = BusinessPartnerProjection(
        legal_entity_id=request.legal_entity_id.strip(),
        business_partner_id=public_id,
        roles=tuple(request.roles),
        display_name=request.display_name.strip(),
        status=request.status,
        revision=revision,
        source_customer_id=None,
        billing_country=request.billing_country.upper() if request.billing_country else None,
        default_currency=request.default_currency.upper() if request.default_currency else None,
    )
    return BusinessPartnerProjectionResult(
        projection=projection,
        created=result.created,
        reused=result.reused,
        updated=result.updated,
        native_record_id=native_id,
    )
