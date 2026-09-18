import unittest
from dataclasses import dataclass

from provisioning.idempiere_adapter import IdempiereProvisioningAdapter
from provisioning.model import ProvisioningStep, StepKind


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 100

    def create_record(self, table, fields):
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def update_record(self, table, record_id, fields):
        self.records[(table, record_id)].update(fields)

    def execute_process(self, process_id, parameters):
        return {"process_id": process_id, "ok": True}


class FakeMappings:
    def __init__(self):
        self.values = {}

    def get_native_id(self, *, provisioning_id, resource_key):
        return self.values.get((provisioning_id, resource_key))

    def put_native_id(self, *, provisioning_id, resource_key, native_id):
        self.values[(provisioning_id, resource_key)] = native_id


class FakeTenantMappings:
    def __init__(self):
        self.created = []

    def create_mapping(self, tenant_id, entity_id, ad_client_id, ad_org_id):
        self.created.append((tenant_id, entity_id, ad_client_id, ad_org_id))


@dataclass
class Request:
    provisioning_id: str = "p1"
    tenant_id: str = "tenant-zb-za"
    legal_entity_id: str = "le-zb-za"
    legal_name: str = "Zuribeans South Africa"


class IdempiereProvisioningAdapterTests(unittest.TestCase):
    def test_create_client_is_idempotent(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("client", StepKind.CREATE_CLIENT, {})

        first = adapter.apply(request, step)
        second = adapter.apply(request, step)

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(client.records), 1)

    def test_create_organisation_is_idempotent(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("org", StepKind.CREATE_ORGANISATION, {})

        first = adapter.apply(request, step)
        second = adapter.apply(request, step)

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["reused"])

    def test_create_warehouse_is_idempotent(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("warehouse", StepKind.CREATE_WAREHOUSE, {"warehouse_code": "KLA"})

        first = adapter.apply(request, step)
        second = adapter.apply(request, step)

        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["reused"])

    def test_accounting_fails_closed_without_approved_process(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("accounting", StepKind.CONFIGURE_ACCOUNTING, {})

        with self.assertRaises(ValueError):
            adapter.apply(request, step)

    def test_accounting_invokes_configured_process(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("accounting", StepKind.CONFIGURE_ACCOUNTING, {"process_id": 9101})

        result = adapter.apply(request, step)

        self.assertEqual(result["process_id"], 9101)
        self.assertTrue(adapter.check(request, step).ready)

    def test_localisation_fails_closed_without_certified_process(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("localisation", StepKind.CONFIGURE_LOCALISATION, {})

        with self.assertRaises(ValueError):
            adapter.apply(request, step)

    def test_persist_mapping_without_tenant_mappings_still_marks_applied(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("mapping", StepKind.PERSIST_MAPPING, {
            "tenant_id": request.tenant_id, "legal_entity_id": request.legal_entity_id,
        })

        result = adapter.apply(request, step)

        self.assertTrue(result["persisted"])
        self.assertNotIn("tenant_mapping", result)

    def test_persist_mapping_writes_the_tenant_mapping_context_resolution_needs(self):
        client, mappings, tenant_mappings = FakeClient(), FakeMappings(), FakeTenantMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings, tenant_mappings=tenant_mappings)
        request = Request()

        client_step = ProvisioningStep("client", StepKind.CREATE_CLIENT, {})
        created = adapter.apply(request, client_step)

        mapping_step = ProvisioningStep("mapping", StepKind.PERSIST_MAPPING, {
            "tenant_id": request.tenant_id, "legal_entity_id": request.legal_entity_id,
        })
        result = adapter.apply(request, mapping_step)

        self.assertEqual(tenant_mappings.created, [(request.tenant_id, request.legal_entity_id, created["id"], 0)])
        self.assertEqual(result["tenant_mapping"], {"ad_client_id": created["id"], "ad_org_id": 0})

    def test_persist_mapping_with_tenant_mappings_before_create_client_fails_closed(self):
        client, mappings, tenant_mappings = FakeClient(), FakeMappings(), FakeTenantMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings, tenant_mappings=tenant_mappings)
        request = Request()
        step = ProvisioningStep("mapping", StepKind.PERSIST_MAPPING, {
            "tenant_id": request.tenant_id, "legal_entity_id": request.legal_entity_id,
        })

        with self.assertRaises(ValueError):
            adapter.apply(request, step)

    def test_check_reports_not_ready_before_apply(self):
        client, mappings = FakeClient(), FakeMappings()
        adapter = IdempiereProvisioningAdapter(client, mappings)
        request = Request()
        step = ProvisioningStep("client", StepKind.CREATE_CLIENT, {})

        self.assertFalse(adapter.check(request, step).ready)


if __name__ == "__main__":
    unittest.main()
