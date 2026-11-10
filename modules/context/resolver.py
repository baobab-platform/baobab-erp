from typing import Protocol

from context.model import ContextResolutionError, TenantContext


class TenantMappingStore(Protocol):
    """Backing store for active tenant/legal-entity -> AD_Client/AD_Org mappings.

    A real implementation queries the mapping schema in db/migrations; tests use an
    in-memory fake. Neither this protocol nor its callers assume tenant_id == AD_Client_ID
    (ADR-ERP-002).
    """

    def find_active_mapping(self, tenant_id: str, entity_id: str) -> tuple[int, int] | None: ...

    def find_by_native(self, ad_client_id: int, ad_org_id: int) -> tuple[str, str] | None: ...


def resolve_context(
    tenant_id: str | None,
    entity_id: str | None,
    store: TenantMappingStore,
) -> TenantContext:
    """Resolve inbound headers into a TenantContext, or raise. Never guesses."""
    if not tenant_id or not entity_id:
        raise ContextResolutionError("Both tenant_id and entity_id are required")

    mapping = store.find_active_mapping(tenant_id, entity_id)
    if mapping is None:
        raise ContextResolutionError(
            f"No active mapping for tenant_id={tenant_id!r} entity_id={entity_id!r}"
        )

    ad_client_id, ad_org_id = mapping
    if ad_client_id <= 0 or ad_org_id < 0:
        raise ContextResolutionError("system/invalid native ERP context is not a business tenant")
    return TenantContext(tenant_id=tenant_id, entity_id=entity_id, ad_client_id=ad_client_id, ad_org_id=ad_org_id)


def resolve_tenant(
    ad_client_id: int,
    ad_org_id: int,
    store: TenantMappingStore,
) -> TenantContext:
    """Resolve an iDempiere-native (AD_Client_ID, AD_Org_ID) pair back to the Baobab
    tenant/legal-entity that owns it, or raise. Never guesses.

    Needed because ADR-ERP-003's default topology (ERP_SHARED_INSTANCE_DEDICATED_CLIENT)
    has one iDempiere runtime hosting several AD_Clients (tenants) at once: code running
    inside that runtime cannot assume a single tenant for the whole process and must
    derive it per record from the record's own AD_Client_ID/AD_Org_ID.
    """
    if ad_client_id <= 0 or ad_org_id < 0:
        raise ContextResolutionError("system/invalid native ERP context is not a business tenant")
    mapping = store.find_by_native(ad_client_id, ad_org_id)
    if mapping is None:
        raise ContextResolutionError(
            f"No active mapping for ad_client_id={ad_client_id!r} ad_org_id={ad_org_id!r}"
        )

    tenant_id, entity_id = mapping
    return TenantContext(tenant_id=tenant_id, entity_id=entity_id, ad_client_id=ad_client_id, ad_org_id=ad_org_id)
