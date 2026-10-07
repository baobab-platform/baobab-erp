"""POST/GET /provisioning-operations against real Postgres (handler level: the append-only baseline and command
tables are never committed, every test rolls back) plus HTTP-level checks of the wiring that need no committed data."""
import json
import sys
import uuid
import unittest
from pathlib import Path
from datetime import date, datetime, timezone

from application.provisioning_operations import (
    ProvisioningDependencies, get_provisioning_operation, request_provisioning)
from provisioning.control_plane_client import AssignmentNotEstablished, ControlPlaneUnavailable
from provisioning.cp_contract import assignment_from_payload
from provisioning.finance_baseline_store import PostgresFinanceBaselineStore
from provisioning.legal_entity_policy import ConfiguredNativePlacementPolicy, NativeClientMode, NativePlacement

# CI discovers this directory with only modules/ on the path; the assignment fixtures live with the unit tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from _postgres import connect  # noqa: E402
from test_cp_authoritative_assignment import DIGEST, MARKETS, payload

NOW = datetime(2026, 10, 2, 9, 5, tzinfo=timezone.utc)
KEY = "idem-" + "0123456789abcdef"


class StubControlPlane:
    def __init__(self, bodies=None, error=None):
        self.bodies = bodies or {}
        self.error = error
        self.calls = []

    def resolve_erp_assignment(self, *, tenant_id, tenant_provisioning_id, legal_entity_id):
        self.calls.append((tenant_id, tenant_provisioning_id, legal_entity_id))
        if self.error:
            raise self.error
        return assignment_from_payload(self.bodies[legal_entity_id])


class ProvisioningOperationTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self._rollback)
        suffix = uuid.uuid4().hex[:8].upper()
        self.entity = f"ZB-{suffix}"
        self.tenant = "tn_01k4zuribeans"
        self.body = payload(entity=self.entity)
        PostgresFinanceBaselineStore(self.connection).record(
            legal_entity_id=self.entity, functional_currency="ZAR", fiscal_year_start_month=1,
            chart_of_accounts_template="coa-zb-v1", accounting_schema="ZB Primary", tax_profile="tax-za-v1",
            costing_method="average-po", effective_from=date(2026, 10, 1), approved_by="Thandi Nkosi",
            approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc), evidence_reference="FIN-CHG-2026-114",
            now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))
        self.control_plane = StubControlPlane({self.entity: self.body})
        self.deps = ProvisioningDependencies(
            control_plane=self.control_plane,
            native_placement=ConfiguredNativePlacementPolicy(
                {self.entity: NativePlacement("Zuribeans_ZA", NativeClientMode.DEDICATED_CLIENT)}),
            market_configuration=MARKETS, target_environment="production", now=lambda: NOW)

    def _rollback(self):
        self.connection.rollback()
        self.connection.close()

    def request(self, **overrides):
        document = {
            "tenant_id": self.tenant, "context_id": str(uuid.uuid4()), "legal_entity_ids": [self.entity], "requested_countries": ["ZA"],
            "functional_currencies": ["ZAR"],
            "control_plane_authority": {
                "tenant_provisioning_id": self.body["tenant_provisioning_id"], "plan_id": self.body["plan_id"],
                "plan_version": self.body["plan_version"], "plan_digest": DIGEST}}
        document.update(overrides)
        return document

    def post(self, document=None, key=KEY, tenant=None, deps="default", principal="svc-erp-orchestrator"):
        return request_provisioning(
            tenant_id=tenant or self.tenant, principal=principal,
            body=json.dumps(document if document is not None else self.request()).encode(), idempotency_key=key,
            connection=self.connection, provisioning=self.deps if deps == "default" else deps,
            correlation_id=str(uuid.uuid4()), trace_id=None)

    def get(self, operation_id, tenant=None):
        return get_provisioning_operation(
            tenant_id=tenant or self.tenant, argument=operation_id, connection=self.connection,
            correlation_id=str(uuid.uuid4()), trace_id=None)

    def test_an_exactly_matching_request_is_accepted_and_readable(self):
        status, body, _ = self.post()
        self.assertEqual((status, body["state"], body["legal_entity_ids"]), (202, "accepted", [self.entity]))
        uuid.UUID(body["operation_id"])
        got_status, got = self.get(body["operation_id"])
        self.assertEqual((got_status, got["operation_id"], got["state"]), (200, body["operation_id"], "accepted"))

    def test_a_fresh_context_replays_the_original_operation(self):
        first = self.post()[1]
        status, again, _ = self.post()
        self.assertEqual((status, again["operation_id"]), (202, first["operation_id"]))

    def test_a_key_reused_for_a_different_request_conflicts(self):
        self.post()
        status, body, _ = self.post(self.request(requested_countries=["ZA", "UG"]))
        self.assertEqual((status, body["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))

    def test_the_same_key_by_another_principal_is_a_different_request(self):
        self.post()
        status, body, _ = self.post(principal="svc-other")
        self.assertEqual((status, body["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))

    def test_every_plan_authority_member_is_compared_with_the_approved_plan(self):
        for member, wrong in (("plan_id", "plan_ffffffffffffffff"), ("plan_version", 4),
                              ("plan_digest", "sha256:" + "c3" * 32),
                              ("tenant_provisioning_id", "tp_0199a1b2c3d47e8f9a0b1c2d3e4f5a6c")):
            with self.subTest(member):
                authority = dict(self.request()["control_plane_authority"], **{member: wrong})
                status, body, _ = self.post(self.request(control_plane_authority=authority), key=f"idem-{member}-0123456789")
                self.assertEqual((status, body["code"]), (409, "PLAN_AUTHORITY_MISMATCH"))

    def test_requested_countries_and_currencies_are_intent_not_authority(self):
        for field, value in (("requested_countries", ["UG"]), ("functional_currencies", ["USD"])):
            with self.subTest(field):
                status, body, _ = self.post(self.request(**{field: value}), key=f"idem-{field}-0123456789")
                self.assertEqual((status, body["code"]), (409, "PLAN_AUTHORITY_MISMATCH"))

    def test_no_executable_approved_plan_is_a_conflict(self):
        self.control_plane.error = AssignmentNotEstablished(404, "NOT_FOUND", None)
        status, body, _ = self.post()
        self.assertEqual((status, body["code"]), (409, "PLAN_AUTHORITY_MISMATCH"))

    def test_control_plane_outage_is_503_with_retry_after_and_writes_nothing(self):
        self.control_plane.error = ControlPlaneUnavailable("down")
        status, body, headers = self.post()
        self.assertEqual((status, headers.get("Retry-After")), (503, "30"))
        self.control_plane.error = None
        self.assertEqual(self.post()[0], 202)

    def test_a_missing_finance_baseline_is_a_conflict_not_a_default(self):
        bare = f"ZB-{uuid.uuid4().hex[:8].upper()}"
        self.control_plane.bodies[bare] = payload(entity=bare)
        self.deps = ProvisioningDependencies(
            control_plane=self.control_plane,
            native_placement=ConfiguredNativePlacementPolicy(
                {bare: NativePlacement("Zuribeans_ZA", NativeClientMode.DEDICATED_CLIENT)}),
            market_configuration=MARKETS, target_environment="production", now=lambda: NOW)
        status, body, _ = self.post(self.request(legal_entity_ids=[bare]))
        self.assertEqual((status, body["code"]), (409, "ERP_CONFLICT"))
        self.assertIn("baseline", body["detail"].lower())

    def test_the_validated_context_tenant_is_the_only_tenant_authority(self):
        status, body, _ = self.post(tenant="tn_01k4someoneelse")
        self.assertEqual(status, 403)
        self.assertEqual(self.control_plane.calls, [])

    def test_the_operation_is_invisible_to_another_tenant(self):
        operation = self.post()[1]["operation_id"]
        self.assertEqual(self.get(operation, tenant="tn_01k4someoneelse")[0], 404)

    def test_invalid_input_is_400_and_unconfigured_is_503(self):
        self.assertEqual(self.post(key="short")[0], 400)
        self.assertEqual(self.post(self.request(extra="x"))[0], 400)
        authority = {k: v for k, v in self.request()["control_plane_authority"].items() if k != "plan_digest"}
        self.assertEqual(self.post(self.request(control_plane_authority=authority))[0], 400)
        status, _, headers = self.post(deps=None)
        self.assertEqual((status, headers.get("Retry-After")), (503, "30"))
        self.assertEqual(self.get("op_nope")[0], 400)
        self.assertEqual(self.get(str(uuid.uuid4()))[0], 404)


if __name__ == "__main__":
    unittest.main()
