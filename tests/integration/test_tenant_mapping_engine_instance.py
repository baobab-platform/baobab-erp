"""A provisioned legal entity must carry its EngineInstance in baobab.tenant_mapping.

Everything keyed by the instance (master-data mappings, inventory reads, order execution) resolves the tenant's placement from
that column. PERSIST_MAPPING used to leave it NULL, so a provisioned tenant's order events blocked as TENANT_UNMAPPED. These tests
run the real planner's PERSIST_MAPPING step through the adapter into the real store, then the real order worker over it, and
check the migration that backfills rows written before the fix."""
import json
import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path


from context.postgres_store import PostgresTenantMappingStore
from provisioning.idempiere_adapter import IdempiereProvisioningAdapter
from provisioning.model import AccountingConfiguration, ErpProvisioningRequest, MarketConfiguration, StepKind
from provisioning.planner import build_plan

from test_order_inbox_execution import _Base

MIGRATION = Path(__file__).resolve().parents[2] / "db/migrations/0020_backfill_tenant_mapping_engine_instance.sql"


def valid_request() -> ErpProvisioningRequest:
    return ErpProvisioningRequest(
        provisioning_id="zb-v1", idempotency_key="zb-v1", tenant_id="tn_zb", legal_entity_id="ZURIBEANS",
        legal_name="ZuriBeans Ltd", registration_identifier="reg-1", jurisdiction_code="UG",
        engine_instance_id="ei_zb", isolation_requirement="row_level_security", plan_digest="sha256:" + "b2" * 32,
        target_environment="production", effective_date=date(2026, 10, 1),
        accounting=AccountingConfiguration("UGX", 1, "coa-zb-v1", "ZB Primary", "tax-ug-v1", "average-po", "finance-user",
                                           datetime(2026, 9, 13, tzinfo=timezone.utc)),
        markets=(MarketConfiguration("market-ug", "UG", frozenset({"sourcing", "selling"}), ("UGX", "USD"), "ug-v1", ("KLA",)),),
        requested_capabilities=frozenset({"finance.order-consequence.process"}))


class _Client:
    def __init__(self, ad_client_id):
        self.ad_client_id = ad_client_id

    def create_record(self, table, fields):
        return self.ad_client_id

    def get_record(self, table, record_id):
        return {}


class _Mappings:
    def __init__(self):
        self.values = {}

    def get_native_id(self, *, provisioning_id, resource_key):
        return self.values.get((provisioning_id, resource_key))

    def put_native_id(self, *, provisioning_id, resource_key, native_id):
        self.values[(provisioning_id, resource_key)] = native_id


class ProvisionedTenantExecutesOrdersTests(_Base):
    def test_a_tenant_persisted_by_the_provisioning_step_is_resolved_by_the_order_worker(self):
        self.seed(tenant=False)
        request = replace(valid_request(), tenant_id=self.tenant, legal_entity_id=self.entity,
                          engine_instance_id=self.engine_instance)
        plan = build_plan(request)
        adapter = IdempiereProvisioningAdapter(_Client(self.ad_client), _Mappings(),
                                               tenant_mappings=PostgresTenantMappingStore(self.db))
        for step in plan.steps:
            if step.kind in (StepKind.CREATE_CLIENT, StepKind.PERSIST_MAPPING):
                adapter.apply(request, step)
        self.db.commit()
        self.assertEqual(self.scalar("SELECT engine_instance_id FROM baobab.tenant_mapping WHERE tenant_id = %s", self.tenant),
                         self.engine_instance)

        wire = self.placed()
        self.deliver(wire)
        self.work()

        self.assertEqual(self.row(wire["id"])["code"], "EXECUTED")  # not TENANT_UNMAPPED
        self.assertEqual(len(self.engine_orders()), 1)

    def test_the_store_refuses_a_mapping_without_an_engine_instance(self):
        store = PostgresTenantMappingStore(self.db)
        for blank in ("", "   ", None):
            with self.subTest(blank), self.assertRaises(ValueError):
                store.create_mapping(self.tenant, self.entity, self.ad_client, 0, blank)
        self.assertEqual(self.scalar("SELECT count(*) FROM baobab.tenant_mapping WHERE tenant_id = %s", self.tenant), 0)


class BackfillMigrationTests(_Base):
    def setUp(self):
        super().setUp()
        self.operations = []
        self.addCleanup(self._drop_operations)

    def _drop_operations(self):
        self.db.rollback()
        with self.db.cursor() as cursor:
            for provisioning_id in self.operations:
                cursor.execute("DELETE FROM baobab.erp_provisioning_operation WHERE provisioning_id = %s", (provisioning_id,))
        self.db.commit()

    def _mapping(self, entity, ad_client, instance=None):
        with self.db.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, engine_instance_id) "
                           "VALUES (%s,%s,%s,0,%s)", (self.tenant, entity, ad_client, instance))
        self.db.commit()

    def _operation(self, entity, instance, status="active"):
        provisioning_id = f"prov_{uuid.uuid4().hex[:12]}"
        self.operations.append(provisioning_id)
        state = {"tenant_id": self.tenant, "legal_entity_id": entity}
        if instance is not None:
            state["engine_instance_id"] = instance
        with self.db.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.erp_provisioning_operation (provisioning_id, idempotency_key, desired_state, status) "
                           "VALUES (%s,%s,%s::jsonb,%s)", (provisioning_id, provisioning_id, json.dumps(state), status))
        self.db.commit()

    def _instance(self, entity):
        return self.scalar("SELECT engine_instance_id FROM baobab.tenant_mapping WHERE tenant_id = %s AND entity_id = %s",
                           self.tenant, entity)

    def test_it_fills_only_what_the_provisioning_records_state_unambiguously(self):
        base = self.ad_client
        self._mapping("ALPHA", base + 1)           # one operation names an instance: filled
        self._operation("ALPHA", "ei_alpha")
        self._mapping("BRAVO", base + 2)           # two operations agree: filled
        self._operation("BRAVO", "ei_bravo")
        self._operation("BRAVO", "ei_bravo", status="ready")
        self._mapping("CHARLIE", base + 3)         # operations disagree: left for an operator
        self._operation("CHARLIE", "ei_one")
        self._operation("CHARLIE", "ei_two")
        self._mapping("DELTA", base + 4)           # no operation at all: left alone
        self._mapping("ECHO", base + 5, "ei_kept") # already set: never overwritten
        self._operation("ECHO", "ei_other")
        self._mapping("FOXTROT", base + 6)         # only a failed operation: not evidence
        self._operation("FOXTROT", "ei_failed", status="failed")
        self._mapping("GOLF", base + 7)            # an operation that names no instance
        self._operation("GOLF", None)
        self._mapping("HOTEL", base + 8)           # one names an instance, another names none: no evidence they agree
        self._operation("HOTEL", "ei_hotel")
        self._operation("HOTEL", None)
        self._mapping("INDIA", base + 9)           # a blank instance counts as none
        self._operation("INDIA", "ei_india")
        self._operation("INDIA", "")

        with self.db.cursor() as cursor:
            cursor.execute(MIGRATION.read_text())
        self.db.commit()

        self.assertEqual({e: self._instance(e) for e in
                          ("ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL", "INDIA")},
                         {"ALPHA": "ei_alpha", "BRAVO": "ei_bravo", "CHARLIE": None, "DELTA": None, "ECHO": "ei_kept",
                          "FOXTROT": None, "GOLF": None, "HOTEL": None, "INDIA": None})

    def test_running_it_twice_changes_nothing_more(self):
        self._mapping("ALPHA", self.ad_client + 1)
        self._operation("ALPHA", "ei_alpha")
        for _ in range(2):
            with self.db.cursor() as cursor:
                cursor.execute(MIGRATION.read_text())
            self.db.commit()
        self.assertEqual(self._instance("ALPHA"), "ei_alpha")


if __name__ == "__main__":
    unittest.main()
