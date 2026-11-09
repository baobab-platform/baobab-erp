import unittest

from context.model import ContextResolutionError, TenantContext
from context.resolver import resolve_context, resolve_tenant


class FakeMappingStore:
    def __init__(self, mappings):
        self._mappings = mappings

    def find_active_mapping(self, tenant_id, entity_id):
        return self._mappings.get((tenant_id, entity_id))

    def find_by_native(self, ad_client_id, ad_org_id):
        for (tenant_id, entity_id), (mapped_client_id, mapped_org_id) in self._mappings.items():
            if (mapped_client_id, mapped_org_id) == (ad_client_id, ad_org_id):
                return (tenant_id, entity_id)
        return None


class ContextResolverTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeMappingStore({("nabhold", "nabhold-legal"): (1000, 1)})

    def test_resolves_active_mapping(self):
        context = resolve_context("nabhold", "nabhold-legal", self.store)
        self.assertEqual(context, TenantContext("nabhold", "nabhold-legal", 1000, 1))

    def test_missing_tenant_id_fails_closed(self):
        with self.assertRaises(ContextResolutionError):
            resolve_context(None, "nabhold-legal", self.store)

    def test_missing_entity_id_fails_closed(self):
        with self.assertRaises(ContextResolutionError):
            resolve_context("nabhold", None, self.store)

    def test_unmapped_pair_fails_closed(self):
        with self.assertRaises(ContextResolutionError):
            resolve_context("nabhold", "unknown-legal-entity", self.store)

    def test_cross_tenant_pair_fails_closed(self):
        """NABHOLD -> THAMANI must never resolve: distinct tenants stay isolated."""
        with self.assertRaises(ContextResolutionError):
            resolve_context("thamani", "nabhold-legal", self.store)

    def test_resolves_tenant_from_native_ids(self):
        context = resolve_tenant(1000, 1, self.store)
        self.assertEqual(context, TenantContext("nabhold", "nabhold-legal", 1000, 1))

    def test_system_client_cannot_be_claimed_as_an_erp_tenant(self):
        store = FakeMappingStore({("tenant", "entity"): (0, 0)})
        with self.assertRaises(ContextResolutionError):
            resolve_context("tenant", "entity", store)
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(0, 0, store)

    def test_negative_native_identifiers_are_not_authority(self):
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(-1, 5, self.store)
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(1000, -1, self.store)

    def test_unmapped_native_ids_fail_closed(self):
        with self.assertRaises(ContextResolutionError):
            resolve_tenant(9999, 9, self.store)


if __name__ == "__main__":
    unittest.main()
