import unittest

from integration.idempiere_client import IdempiereClientError
from provisioning.idempiere_adapter import IdempiereProvisioningAdapter, ProvisioningStepError
from provisioning.model import ProvisioningStep, StepKind
from provisioning.planner import build_plan
from provisioning.service import ErpProvisioningService
from test_provisioning_planner import valid_request
from test_provisioning_service import MemoryStore


class FakeIdempiereClient:
    def __init__(self):
        self.records: dict[tuple[str, int], dict] = {}
        self._next_id = 1000

    def create_record(self, table, fields):
        record_id = self._next_id
        self._next_id += 1
        self.records[(table, record_id)] = {**fields, "IsActive": fields.get("IsActive", "Y")}
        return record_id

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def update_record(self, table, record_id, fields):
        self.records[(table, record_id)].update(fields)

    def execute_process(self, process_id, parameters):
        raise AssertionError("provisioning never invokes native processes")


class FailingIdempiereClient(FakeIdempiereClient):
    def create_record(self, table, fields):
        raise IdempiereClientError("simulated connection failure")


class FakeTenantMappingStore:
    def __init__(self):
        self.mappings: dict[tuple[str, str], tuple[int, int]] = {}

    def create_mapping(self, tenant_id, entity_id, ad_client_id, ad_org_id):
        key = (tenant_id, entity_id)
        if key in self.mappings:
            raise ValueError("mapping already exists")
        self.mappings[key] = (ad_client_id, ad_org_id)

    def find_active_mapping(self, tenant_id, entity_id):
        return self.mappings.get((tenant_id, entity_id))


class IdempiereProvisioningAdapterTests(unittest.TestCase):
    def test_apply_full_plan_creates_client_accounting_localisation_warehouse_and_mapping(self):
        request = valid_request()
        plan = build_plan(request)
        client, mappings = FakeIdempiereClient(), FakeTenantMappingStore()
        adapter = IdempiereProvisioningAdapter(client, mappings)

        for step in plan.steps:
            adapter.apply(request, step)

        client_records = [v for (table, _id), v in client.records.items() if table == "AD_Client"]
        self.assertEqual(len(client_records), 1)
        self.assertEqual(client_records[0]["Name"], request.legal_name)
        self.assertEqual(client_records[0]["AD_Language"], "en_US")

        acct_records = [v for (table, _id), v in client.records.items() if table == "C_AcctSchema"]
        self.assertEqual(len(acct_records), 1)
        self.assertEqual(acct_records[0]["C_Currency_ID"], "UGX")

        warehouse_records = [v for (table, _id), v in client.records.items() if table == "M_Warehouse"]
        self.assertEqual(len(warehouse_records), 1)
        self.assertEqual(warehouse_records[0]["Value"], "KLA")

        mapping = mappings.find_active_mapping(request.tenant_id, request.legal_entity_id)
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping[1], 0)

    def test_readiness_after_full_apply_is_all_ready(self):
        request = valid_request()
        plan = build_plan(request)
        adapter = IdempiereProvisioningAdapter(FakeIdempiereClient(), FakeTenantMappingStore())
        for step in plan.steps:
            adapter.apply(request, step)
        for step in plan.steps:
            self.assertTrue(adapter.check(request, step).ready, step.key)

    def test_configure_accounting_before_create_client_raises(self):
        request = valid_request()
        adapter = IdempiereProvisioningAdapter(FakeIdempiereClient(), FakeTenantMappingStore())
        step = ProvisioningStep("zb-v1:accounting", StepKind.CONFIGURE_ACCOUNTING, {
            "functional_currency": "UGX", "accounting_schema": "ZB Primary",
            "chart_of_accounts_template": "coa-zb-v1", "fiscal_year_start_month": 1,
            "tax_profile": "tax-ug-v1", "costing_method": "average-po",
        })
        with self.assertRaises(ProvisioningStepError):
            adapter.apply(request, step)

    def test_idempiere_client_error_is_wrapped_as_provisioning_step_error(self):
        request = valid_request()
        plan = build_plan(request)
        adapter = IdempiereProvisioningAdapter(FailingIdempiereClient(), FakeTenantMappingStore())
        with self.assertRaises(ProvisioningStepError):
            adapter.apply(request, plan.steps[0])

    def test_full_service_apply_is_retry_safe_with_real_adapter(self):
        request = valid_request()
        store = MemoryStore()
        adapter = IdempiereProvisioningAdapter(FakeIdempiereClient(), FakeTenantMappingStore())
        service = ErpProvisioningService(store, adapter)

        plan = service.plan(request)
        service.apply(request, plan)
        applied_after_first = dict(store.steps)
        service.apply(request, plan)
        self.assertEqual(store.steps, applied_after_first)
        self.assertTrue(service.readiness(request, plan).ready)


if __name__ == "__main__":
    unittest.main()
