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
from application.finance_baselines import get_effective_finance_baseline, get_finance_baseline
from provisioning.finance_baseline import baseline_digest, baseline_id_for, reference_of
from provisioning.finance_baseline_store import PostgresFinanceBaselineStore
from provisioning.legal_entity_policy import ConfiguredNativePlacementPolicy, NativeClientMode, NativePlacement
from security.platform_context import ProvisioningAuthority

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


class _Fixture(unittest.TestCase):
    """One legal entity with a Finance baseline recorded, a stub Control Plane, and the helpers both suites use."""

    def setUp(self):
        self.connection = connect()
        self.addCleanup(self._rollback)
        suffix = uuid.uuid4().hex[:8].upper()
        self.entity = f"ZB-{suffix}"
        self.tenant = "tn_01k4zuribeans"
        self.body = payload(entity=self.entity)
        self.baselines = PostgresFinanceBaselineStore(self.connection)
        self.baseline = self.baselines.record(
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
            "functional_currencies": ["ZAR"], "finance_baselines": [reference_of(self.baseline)],
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

    def authority(self, **overrides):
        """The provisioning context the Control Plane vouches for: bound to the plan this fixture's request names."""
        values = {"tenant_provisioning_id": self.body["tenant_provisioning_id"], "plan_id": self.body["plan_id"],
                  "plan_version": self.body["plan_version"], "plan_digest": DIGEST}
        values.update(overrides)
        return ProvisioningAuthority(**values)

    def get(self, operation_id, tenant=None, authority="bound"):
        return get_provisioning_operation(
            tenant_id=tenant or self.tenant, argument=operation_id, connection=self.connection,
            correlation_id=str(uuid.uuid4()), trace_id=None,
            context_authority=self.authority() if authority == "bound" else authority)

class ProvisioningOperationTests(_Fixture):
    def test_an_exactly_matching_request_is_accepted_and_readable(self):
        status, body, _ = self.post()
        self.assertEqual((status, body["state"], body["legal_entity_ids"]), (202, "accepted", [self.entity]))
        uuid.UUID(body["operation_id"])
        got_status, got = self.get(body["operation_id"])
        self.assertEqual((got_status, got["operation_id"], got["state"]), (200, body["operation_id"], "accepted"))

    def test_an_operation_is_readable_only_under_a_context_bound_to_the_plan_it_was_accepted_under(self):
        operation = self.post()[1]["operation_id"]
        for name, other in {"provisioning": "tp_0199a1b2c3d4ffff", "plan id": "plan_0199a1b2c3d4ffff", "plan version": 99,
                            "plan digest": "sha256:" + "ee" * 32}.items():
            key = {"provisioning": "tenant_provisioning_id", "plan id": "plan_id", "plan version": "plan_version",
                   "plan digest": "plan_digest"}[name]
            with self.subTest(name):
                status, body = self.get(operation, authority=self.authority(**{key: other}))
                self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
        # A context that carries no plan (a RUNTIME one) is refused the same way, however it reached here.
        status, body = self.get(operation, authority=None)
        self.assertEqual((status, body["code"]), (403, "ERP_CONTEXT_REJECTED"))
        # Absence stays absence: another tenant's operation and an unknown one are 404 whatever plan the context carries.
        self.assertEqual(self.get(operation, tenant="tn_01k4someoneelse")[0], 404)
        self.assertEqual(self.get(str(uuid.uuid4()), authority=None)[0], 404)

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
        # No baseline exists for this entity, so any reference to one is a reference to something ERP does not hold.
        invented = dict(reference_of(self.baseline), legal_entity_id=bare, baseline_id=baseline_id_for(bare))
        status, body, _ = self.post(self.request(legal_entity_ids=[bare], finance_baselines=[invented]))
        self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))

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


class FinanceBaselineTests(_Fixture):
    """FB-02 (Shared erp/v1 1.3.0): a provisioning REFERS to an exact approved baseline version, ERP re-resolves it, and the
    two reads resolve a reference."""

    def record(self, version_effective, *, currency="ZAR", approved=datetime(2026, 9, 2, tzinfo=timezone.utc)):
        return self.baselines.record(
            legal_entity_id=self.entity, functional_currency=currency, fiscal_year_start_month=1,
            chart_of_accounts_template="coa-zb-v2", accounting_schema="ZB Primary", tax_profile="tax-za-v1",
            costing_method="average-po", effective_from=version_effective, approved_by="Thandi Nkosi", approved_at=approved,
            evidence_reference="FIN-CHG-2026-200", now=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))

    def effective(self, entity=None, on=None, authority="bound", tenant=None):
        query = f"effective_on={on}" if on else ""
        return get_effective_finance_baseline(
            tenant_id=tenant or self.tenant, argument=entity or self.entity, query_string=query, connection=self.connection,
            correlation_id=str(uuid.uuid4()), trace_id=None,
            context_authority=self.authority() if authority == "bound" else authority, provisioning=self.deps)

    def exact(self, reference=None, authority="bound", query=None, argument=None):
        reference = reference or reference_of(self.baseline)
        if query is None:
            query = f"version={reference['version']}&digest={reference['digest']}"
        return get_finance_baseline(
            tenant_id=self.tenant, argument=argument or reference["baseline_id"], query_string=query, connection=self.connection,
            correlation_id=str(uuid.uuid4()), trace_id=None,
            context_authority=self.authority() if authority == "bound" else authority, provisioning=self.deps)

    # --- the reference and its digest -----------------------------------------------------------------------------------

    def test_the_lineage_id_is_stable_across_versions_and_found_again_from_the_database(self):
        later = self.record(date(2026, 11, 1))
        self.assertEqual(baseline_id_for(self.entity), reference_of(later)["baseline_id"])
        self.assertEqual(reference_of(later)["baseline_id"], reference_of(self.baseline)["baseline_id"])
        # The SQL expression and the Python one are the same function, or lookups would silently miss.
        self.assertEqual(self.baselines.legal_entity_of(baseline_id_for(self.entity)), self.entity)
        self.assertIsNone(self.baselines.legal_entity_of(baseline_id_for("NOBODY-ZZ")))

    def test_the_digest_names_exactly_the_approved_content(self):
        from dataclasses import replace
        base = baseline_digest(self.baseline)
        self.assertEqual(base, baseline_digest(self.baselines.get(self.entity, self.baseline.version)))
        for field, value in {"functional_currency": "USD", "fiscal_year_start_month": 4, "chart_of_accounts_template": "x",
                             "accounting_schema": "x", "tax_profile": "x", "costing_method": "x", "approved_by": "Someone Else",
                             "evidence_reference": "FIN-X", "version": 9, "effective_from": date(2027, 1, 1),
                             "approved_at": datetime(2026, 9, 2, tzinfo=timezone.utc)}.items():
            with self.subTest(field):
                self.assertNotEqual(base, baseline_digest(replace(self.baseline, **{field: value})))
        self.assertRegex(base, r"^sha256:[0-9a-f]{64}$")

    # --- standing -------------------------------------------------------------------------------------------------------

    def test_a_version_is_effective_superseded_not_yet_effective_or_withdrawn(self):
        v1 = self.baseline
        v2 = self.record(date(2026, 10, 2))
        v3 = self.record(date(2026, 12, 1))
        today = NOW.date()
        self.assertEqual([self.baselines.status(v, today) for v in (v1, v2, v3)], ["SUPERSEDED", "EFFECTIVE", "NOT_YET_EFFECTIVE"])
        self.baselines.withdraw(legal_entity_id=self.entity, version=2, withdrawn_by="Thandi Nkosi", withdrawn_at=NOW,
                                reason="mis-stated tax profile", evidence_reference="FIN-CHG-2026-201", now=NOW)
        # A withdrawn approval is not in force, so the version before it governs again; the withdrawn one is still readable.
        self.assertEqual([self.baselines.status(v, today) for v in (v1, v2, v3)], ["EFFECTIVE", "WITHDRAWN", "NOT_YET_EFFECTIVE"])
        self.assertEqual(self.baselines.effective(self.entity, today).version, 1)
        self.assertEqual(self.baselines.get(self.entity, 2).version, 2)

    def test_a_withdrawal_is_a_named_persons_append_only_fact(self):
        from provisioning.finance_baseline_store import FinanceBaselineError
        for who in ("system", "  ", "REQUIRED_X"):
            with self.subTest(who), self.assertRaises(FinanceBaselineError):
                self.baselines.withdraw(legal_entity_id=self.entity, version=1, withdrawn_by=who, withdrawn_at=NOW, reason="r",
                                        evidence_reference="e", now=NOW)
        with self.assertRaises(FinanceBaselineError):
            self.baselines.withdraw(legal_entity_id=self.entity, version=1, withdrawn_by="Thandi Nkosi",
                                    withdrawn_at=datetime(2027, 1, 1, tzinfo=timezone.utc), reason="r", evidence_reference="e", now=NOW)
        self.baselines.withdraw(legal_entity_id=self.entity, version=1, withdrawn_by="Thandi Nkosi", withdrawn_at=NOW, reason="r",
                                evidence_reference="FIN-1", now=NOW)
        import psycopg
        for statement in ("UPDATE baobab.financial_configuration_baseline_withdrawal SET reason = 'x'",
                          "DELETE FROM baobab.financial_configuration_baseline_withdrawal"):
            with self.subTest(statement):
                with self.assertRaises(psycopg.errors.RestrictViolation):
                    with self.connection.transaction():
                        self.connection.execute(statement)

    # --- getEffectiveFinanceBaseline ------------------------------------------------------------------------------------

    def test_the_effective_read_names_the_version_in_force_and_discloses_only_the_currency(self):
        status, body = self.effective()
        self.assertEqual(status, 200)
        self.assertEqual(body["reference"], reference_of(self.baseline))
        self.assertEqual((body["status"], body["functional_currency"], body["resolved_at"]), ("EFFECTIVE", "ZAR", "2026-10-02T09:05:00Z"))
        self.assertEqual(sorted(body), ["functional_currency", "reference", "resolved_at", "status"])
        for private in ("chart_of_accounts_template", "tax_profile", "approved_by", "evidence_reference"):
            self.assertNotIn(private, str(body))

    def test_the_effective_read_never_invents_a_baseline(self):
        # Before the first version starts, nothing is in force: 404, never a default.
        status, body = self.effective(on="2026-09-30")
        self.assertEqual(status, 404)
        status, body = self.effective(on="2026-10-01")
        self.assertEqual(status, 200)

    def test_the_effective_read_is_for_legal_entities_of_the_context_provisioning_only(self):
        self.control_plane.error = AssignmentNotEstablished(404, "LEGAL_ENTITY_NOT_FOUND", None)
        self.assertEqual(self.effective()[0], 404)
        self.control_plane.error = None
        # A context bound to another plan than the one Control Plane would assign is the same absence.
        self.assertEqual(self.effective(authority=self.authority(plan_id="plan_0199a1b2c3d4ffff"))[0], 404)
        self.assertEqual(self.effective(authority=None)[0], 404)
        self.assertEqual(self.effective(tenant="tn_01k4someoneelse")[0], 404)

    def test_the_effective_read_distinguishes_unavailable_from_absent_and_validates_input(self):
        self.control_plane.error = ControlPlaneUnavailable("down")
        status, body, headers = self.effective()
        self.assertEqual((status, headers["Retry-After"]), (503, "30"))
        self.control_plane.error = None
        for argument, on in (("lower-case", None), ("X", None), (self.entity, "2026-13-40"), (self.entity, "yesterday")):
            with self.subTest((argument, on)):
                self.assertEqual(self.effective(entity=argument, on=on)[0], 400)

    # --- getFinanceBaseline ---------------------------------------------------------------------------------------------

    def test_the_exact_read_resolves_exactly_the_version_and_digest_named(self):
        self.record(date(2026, 10, 2))
        status, body = self.exact()
        self.assertEqual(status, 200)
        self.assertEqual((body["reference"], body["status"]), (reference_of(self.baseline), "SUPERSEDED"))

    def test_the_exact_read_is_never_the_latest(self):
        reference = reference_of(self.baseline)
        for name, query in {"no version": f"digest={reference['digest']}", "no digest": "version=1",
                            "neither": "", "zero": f"version=0&digest={reference['digest']}",
                            "short digest": "version=1&digest=sha256:abc", "unknown parameter": f"version=1&digest={reference['digest']}&latest=1",
                            "two versions": f"version=1&version=2&digest={reference['digest']}"}.items():
            with self.subTest(name):
                self.assertEqual(self.exact(query=query)[0], 400)

    def test_a_known_baseline_with_another_version_or_digest_is_a_mismatch_not_a_fallback(self):
        reference = reference_of(self.baseline)
        status, body = self.exact(query=f"version=1&digest=sha256:{'ab' * 32}")
        self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))
        status, body = self.exact(query=f"version=7&digest={reference['digest']}")
        self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))

    def test_an_unknown_baseline_or_one_outside_the_provisioning_is_absent(self):
        reference = reference_of(self.baseline)
        self.assertEqual(self.exact(argument="fb_" + "0" * 32)[0], 404)
        self.control_plane.error = AssignmentNotEstablished(404, "LEGAL_ENTITY_NOT_FOUND", None)
        self.assertEqual(self.exact()[0], 404)
        self.control_plane.error = None
        self.assertEqual(self.exact(authority=None)[0], 404)
        self.assertEqual(self.exact(argument="NOT-AN-ID")[0], 400)

    def test_a_withdrawn_version_is_returned_with_its_standing(self):
        self.baselines.withdraw(legal_entity_id=self.entity, version=1, withdrawn_by="Thandi Nkosi", withdrawn_at=NOW, reason="r",
                                evidence_reference="FIN-1", now=NOW)
        status, body = self.exact()
        self.assertEqual((status, body["status"]), (200, "WITHDRAWN"))

    # --- POST /provisioning-operations ----------------------------------------------------------------------------------

    def test_a_request_without_finance_baselines_is_an_invalid_document(self):
        document = self.request()
        del document["finance_baselines"]
        status, body, _ = self.post(document)
        self.assertEqual(status, 400)
        self.assertIn("finance_baselines", [error["field"] for error in body["errors"]])

    def test_a_reference_ERP_does_not_hold_exactly_provisions_nothing(self):
        reference = reference_of(self.baseline)
        wrong = {"another digest": dict(reference, digest="sha256:" + "ab" * 32), "another version": dict(reference, version=7),
                 "another baseline": dict(reference, baseline_id="fb_" + "1" * 32),
                 "another start date": dict(reference, effective_from="2026-09-30")}
        for name, bad in wrong.items():
            with self.subTest(name):
                status, body, _ = self.post(self.request(finance_baselines=[bad]), key=f"idem-{name.replace(' ', '-')}-0123456789")
                self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))
        # Nothing was written for any of them.
        status, accepted, _ = self.post(key="idem-after-0123456789")
        self.assertEqual(status, 202)

    def test_the_references_must_be_exactly_one_per_requested_legal_entity(self):
        other = dict(reference_of(self.baseline), legal_entity_id="OTHER-ZA", baseline_id=baseline_id_for("OTHER-ZA"))
        for name, refs in {"an extra reference": [reference_of(self.baseline), other], "a reference for another entity": [other]}.items():
            with self.subTest(name):
                status, body, _ = self.post(self.request(finance_baselines=refs), key=f"idem-{name.replace(' ', '-')}-0123456789")
                self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))

    def test_a_real_baseline_for_an_entity_that_was_not_requested_or_a_missing_one_is_refused(self):
        # Both entities have real, effective baselines and a Control Plane assignment, so only the SET of references is wrong.
        other = f"ZB-{uuid.uuid4().hex[:8].upper()}"
        self.control_plane.bodies[other] = payload(entity=other)
        other_baseline = self.baselines.record(
            legal_entity_id=other, functional_currency="ZAR", fiscal_year_start_month=1, chart_of_accounts_template="coa",
            accounting_schema="s", tax_profile="t", costing_method="c", effective_from=date(2026, 10, 1), approved_by="Thandi Nkosi",
            approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc), evidence_reference="FIN-9", now=NOW)
        self.deps = ProvisioningDependencies(
            control_plane=self.control_plane,
            native_placement=ConfiguredNativePlacementPolicy({
                self.entity: NativePlacement("Zuribeans_ZA", NativeClientMode.DEDICATED_CLIENT),
                other: NativePlacement("Zuribeans_ZB", NativeClientMode.DEDICATED_CLIENT)}),
            market_configuration=MARKETS, target_environment="production", now=lambda: NOW)
        both = [reference_of(self.baseline), reference_of(other_baseline)]
        status, body, _ = self.post(self.request(finance_baselines=both), key="idem-extra-ref-0123456789")
        self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))
        status, body, _ = self.post(self.request(legal_entity_ids=[self.entity, other], finance_baselines=[both[0]]),
                                    key="idem-missing-ref-0123456789")
        self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_MISMATCH"))

    def test_a_reference_must_name_the_baseline_ERP_owns(self):
        for bad in ({"authority": {"engine_id": "baobab-cp", "system_of_record": "FINANCE_BASELINE"}},
                    {"authority": {"engine_id": "baobab-erp", "system_of_record": "OTHER"}}, {"chart_of_accounts_template": "x"}):
            with self.subTest(bad):
                status, body, _ = self.post(self.request(finance_baselines=[dict(reference_of(self.baseline), **bad)]))
                self.assertEqual(status, 400)
                self.assertTrue(all(error["field"].startswith("finance_baselines[0]") for error in body["errors"]))

    def test_a_withdrawn_superseded_or_future_version_is_not_usable(self):
        v1 = reference_of(self.baseline)
        v2 = self.record(date(2026, 10, 2))
        v3 = self.record(date(2026, 12, 1))
        for name, version in {"superseded": reference_of(self.baseline), "not yet effective": reference_of(v3)}.items():
            with self.subTest(name):
                status, body, _ = self.post(self.request(finance_baselines=[version]), key=f"idem-{name.replace(' ', '-')}-0123456789")
                self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_NOT_USABLE"))
        self.baselines.withdraw(legal_entity_id=self.entity, version=2, withdrawn_by="Thandi Nkosi", withdrawn_at=NOW, reason="r",
                                evidence_reference="FIN-1", now=NOW)
        status, body, _ = self.post(self.request(finance_baselines=[reference_of(v2)]), key="idem-withdrawn-0123456789")
        self.assertEqual((status, body["code"]), (409, "FINANCE_BASELINE_NOT_USABLE"))
        # With v2 withdrawn, v1 is in force again and is usable.
        status, _, _ = self.post(self.request(finance_baselines=[v1]), key="idem-v1-again-0123456789")
        self.assertEqual(status, 202)

    def test_the_currencies_must_be_those_of_the_referenced_baselines(self):
        status, body, _ = self.post(self.request(functional_currencies=["USD"]))
        self.assertEqual((status, body["code"]), (409, "PLAN_AUTHORITY_MISMATCH"))

    def test_provisioning_uses_the_referenced_version_not_whatever_is_held_now(self):
        # A later, different version exists but is not yet in force; the request references v1, so v1's currency governs.
        self.record(date(2026, 12, 1), currency="USD")
        status, body, _ = self.post()
        self.assertEqual(status, 202)
        row = self.connection.execute("SELECT finance_baselines FROM baobab.erp_provisioning_command WHERE operation_id = %s",
                                      (body["operation_id"],)).fetchone()[0]
        self.assertEqual(row, [reference_of(self.baseline)])
        desired = self.connection.execute(
            "SELECT desired_state->'accounting'->>'functional_currency' FROM baobab.erp_provisioning_operation ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        self.assertEqual(desired, "ZAR")

    def test_a_different_baseline_reference_is_a_different_request(self):
        self.post()
        v2 = self.record(date(2026, 10, 2))
        status, body, _ = self.post(self.request(finance_baselines=[reference_of(v2)]))
        self.assertEqual((status, body["code"]), (409, "IDEMPOTENCY_KEY_REUSED"))
