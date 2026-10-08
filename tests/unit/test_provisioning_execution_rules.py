"""The pure rules of provisioning execution: what a pass is allowed to start, how its failures are classified, and how the stored
request is proven to be the approved one. No database; the Postgres behaviour is tests/integration/test_provisioning_execution.py."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from integration.idempiere_client import IdempiereApiError, IdempiereAuthenticationError, IdempiereClientError
from provisioning.execution import (
    MAX_ATTEMPTS, BLOCKED_DELAY_SECONDS, BLOCKED_HORIZON, EngineUnconfigured, LoadedOperation, MappingConflict, Outcome,
    ProvisioningExecutor, apply_budgets, classify)
from provisioning.idempiere_adapter import DuplicateNativeRecords
from provisioning.model import ProvisioningStatus
from provisioning.native_processes import NativeProvisioningProcesses, ProcessUnconfigured, load_native_processes
from provisioning.planner import build_plan, desired_state_digest, desired_state_json
from provisioning.request_state import StateDrift, StateUnreadable, request_from_state, verified_request
from provisioning.validation import InvalidProvisioningRequestError

from test_idempiere_provisioning_adapter import FakeClient, FakeMappings, FakeTenantMappings
from test_provisioning_planner import valid_request

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
PROCESSES = NativeProvisioningProcesses(9001, {"UG": 9002})


class FakeStore:
    def __init__(self, done=()):
        self.done, self.statuses, self.results = set(done), [], {}

    def completed_steps(self, provisioning_id):
        return frozenset(self.done)

    def mark_step(self, provisioning_id, step_key, status, result):
        self.done.add(step_key)
        self.results[step_key] = result

    def set_status(self, provisioning_id, status, error=None):
        self.statuses.append(status)


def operation(request=None, *, state_edit=None, plan_edit=None, status="planned", attempts=1):
    request = request or valid_request()
    state = json.loads(desired_state_json(request))
    plan = [{"key": s.key, "kind": s.kind.value, "payload": dict(s.payload)} for s in build_plan(request).steps]
    if state_edit:
        state.update(state_edit)
    if plan_edit:
        plan_edit(plan)
    return LoadedOperation(request.provisioning_id, state, desired_state_digest(request), tuple(plan), status, attempts, NOW)


def executor(client=None, *, store=None, processes=PROCESSES, engine=True, mappings=None):
    client = client if client is not None else FakeClient()
    store = store if store is not None else FakeStore()
    return ProvisioningExecutor(store=store, mappings=mappings if mappings is not None else FakeMappings(),
                                tenant_mappings=FakeTenantMappings(),
                                engine_for=(lambda engine_instance_id: client) if engine else (lambda engine_instance_id: None),
                                processes=processes), client, store


class StoredRequestTests(unittest.TestCase):
    def test_the_request_survives_storage_exactly(self):
        request = valid_request()
        again = request_from_state(json.loads(desired_state_json(request)))
        self.assertEqual(again, request)
        self.assertEqual(desired_state_digest(again), desired_state_digest(request))

    def test_a_request_that_does_not_reproduce_its_digest_is_refused(self):
        state = json.loads(desired_state_json(valid_request()))
        state["legal_name"] = "Someone Else Ltd"
        with self.assertRaises(StateDrift):
            verified_request(state, desired_state_digest(valid_request()))
        with self.assertRaises(StateDrift):
            verified_request(json.loads(desired_state_json(valid_request())), None)  # accepted under no digest at all

    def test_unreadable_state_is_named_not_guessed(self):
        for state in ({}, {"provisioning_id": "x"}, {**json.loads(desired_state_json(valid_request())), "effective_date": "not a date"}):
            with self.subTest(state=list(state)[:2]):
                with self.assertRaises(StateUnreadable):
                    request_from_state(state)


class ClassificationTests(unittest.TestCase):
    def test_each_failure_has_one_fixed_outcome(self):
        cases = [
            (StateDrift("x"), ("failed", "STATE_DRIFT")), (StateUnreadable("x"), ("failed", "STATE_UNREADABLE")),
            (EngineUnconfigured("ei"), ("blocked", "ENGINE_UNCONFIGURED")), (ProcessUnconfigured("x"), ("blocked", "PROCESS_UNCONFIGURED")),
            (IdempiereAuthenticationError("x"), ("blocked", "ENGINE_AUTH")),
            (IdempiereApiError(503, "t", "d"), ("retry", "ENGINE_UNAVAILABLE")), (IdempiereApiError(429, "t", "d"), ("retry", "ENGINE_UNAVAILABLE")),
            (IdempiereApiError(400, "t", "d"), ("failed", "ENGINE_REJECTED")), (IdempiereApiError(422, "t", "d"), ("failed", "ENGINE_REJECTED")),
            (IdempiereClientError("connection reset"), ("retry", "ENGINE_UNAVAILABLE")),
            (DuplicateNativeRecords("x"), ("failed", "DUPLICATE_NATIVE_RECORDS")), (MappingConflict("x"), ("failed", "TENANT_MAPPING_CONFLICT")),
            (ValueError("x"), ("failed", "STEP_INVALID")), (InvalidProvisioningRequestError("x"), ("failed", "STEP_INVALID")),
            (RuntimeError("anything else"), ("retry", "UNEXPECTED_ERROR")),
        ]
        for exc, expected in cases:
            with self.subTest(type(exc).__name__, status=getattr(exc, "status", None)):
                outcome = classify(exc)
                self.assertEqual((outcome.status, outcome.code), expected)

    def test_an_engine_message_is_never_carried_into_the_outcome(self):
        outcome = classify(IdempiereApiError(400, "Bad", "customer Acme Ltd, tax id 12345 rejected"))
        self.assertNotIn("Acme", outcome.detail + outcome.code)
        self.assertEqual(classify(RuntimeError("value-from-the-engine")).detail, "RuntimeError")


class BudgetTests(unittest.TestCase):
    def test_retries_back_off_and_are_spent(self):
        retry = Outcome("retry", "ENGINE_UNAVAILABLE")
        first = apply_budgets(retry, attempts=1, created_at=NOW, now=NOW)
        later = apply_budgets(retry, attempts=5, created_at=NOW, now=NOW)
        self.assertEqual((first.status, first.delay_seconds), ("retry", 30))
        self.assertGreater(later.delay_seconds, first.delay_seconds)
        spent = apply_budgets(retry, attempts=MAX_ATTEMPTS, created_at=NOW, now=NOW)
        self.assertEqual((spent.status, spent.code, spent.detail), ("failed", "ATTEMPTS_EXHAUSTED", "ENGINE_UNAVAILABLE"))

    def test_a_block_is_retried_slowly_until_its_horizon(self):
        blocked = Outcome("blocked", "ENGINE_UNCONFIGURED")
        self.assertEqual(apply_budgets(blocked, attempts=3, created_at=NOW, now=NOW).delay_seconds, BLOCKED_DELAY_SECONDS)
        past = apply_budgets(blocked, attempts=3, created_at=NOW, now=NOW + BLOCKED_HORIZON + timedelta(seconds=1))
        self.assertEqual((past.status, past.code), ("failed", "BLOCKED_HORIZON_EXCEEDED"))

    def test_ready_and_failed_pass_through(self):
        for outcome in (Outcome("ready", "READY"), Outcome("failed", "STATE_DRIFT")):
            self.assertEqual(apply_budgets(outcome, attempts=99, created_at=NOW, now=NOW + timedelta(days=30)), outcome)


class NativeProcessTests(unittest.TestCase):
    def test_configuration_is_all_or_nothing(self):
        self.assertIsNone(load_native_processes({}))
        with self.assertRaises(RuntimeError):
            load_native_processes({"IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING": "9001"})
        with self.assertRaises(RuntimeError):
            load_native_processes({"IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON": '{"UG": 9002}'})
        with self.assertRaises(RuntimeError):
            load_native_processes({"IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING": "x", "IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON": "{}"})
        loaded = load_native_processes({"IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING": "9001",
                                        "IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON": '{"UG": 9002}'})
        self.assertEqual(loaded, NativeProvisioningProcesses(9001, {"UG": 9002}))

    def test_a_country_with_no_certified_process_is_refused(self):
        steps = {s.kind.value: s for s in build_plan(valid_request()).steps}
        with self.assertRaises(ProcessUnconfigured):
            NativeProvisioningProcesses(9001, {"ZA": 1}).enrich(steps["configure_localisation"])


class ExecutorTests(unittest.TestCase):
    def test_an_approved_operation_is_provisioned_and_reported_ready(self):
        runner, client, store = executor()
        outcome = runner.run(operation())
        self.assertEqual((outcome.status, outcome.code), ("ready", "READY"))
        self.assertEqual(store.statuses, [ProvisioningStatus.APPLYING, ProvisioningStatus.RECONCILING, ProvisioningStatus.READY])
        self.assertEqual(len(store.done), len(build_plan(valid_request()).steps))
        self.assertEqual(len([key for key in client.records if key[0] == "AD_Client"]), 1)

    def test_the_planned_steps_get_their_process_ids_from_deployment_configuration(self):
        runner, client, store = executor()
        runner.run(operation())
        ran = {step_result["process_id"] for step_result in store.results.values() if "process_id" in step_result}
        self.assertEqual(ran, {9001, 9002})

    def test_a_missing_process_blocks_before_the_engine_is_touched(self):
        for processes in (None, NativeProvisioningProcesses(9001, {"ZA": 1})):
            with self.subTest(processes=processes):
                runner, client, store = executor(processes=processes)
                outcome = runner.run(operation())
                self.assertEqual((outcome.status, outcome.code), ("blocked", "PROCESS_UNCONFIGURED"))
                self.assertEqual((client.records, store.statuses, store.done), ({}, [], set()))  # no AD_Client left unconfigured

    def test_no_engine_session_blocks_and_touches_nothing(self):
        runner, client, store = executor(engine=False)
        outcome = runner.run(operation())
        self.assertEqual((outcome.status, outcome.code), ("blocked", "ENGINE_UNCONFIGURED"))
        self.assertEqual(store.statuses, [])

    def test_state_that_is_not_what_was_approved_never_reaches_the_engine(self):
        tampered_state = operation(state_edit={"legal_name": "Someone Else Ltd"})
        tampered_plan = operation(plan_edit=lambda plan: plan[0]["payload"].update({"Name": "Someone Else Ltd"}))
        for name, op in {"state": tampered_state, "plan": tampered_plan}.items():
            with self.subTest(name):
                runner, client, store = executor()
                outcome = runner.run(op)
                self.assertEqual((outcome.status, outcome.code), ("failed", "STATE_DRIFT"))
                self.assertEqual((client.records, store.statuses), ({}, []))

    def test_a_restart_resumes_after_the_last_recorded_step(self):
        plan = build_plan(valid_request())
        client, mappings = FakeClient(), FakeMappings()
        executor(client, mappings=mappings)[0].run(operation())  # the whole plan ran once ...
        created = dict(client.records)
        # ... but the process died before the later steps were recorded: only the first two are known to be done.
        runner, _, store = executor(client, store=FakeStore(done=[step.key for step in plan.steps[:2]]), mappings=mappings)
        outcome = runner.run(operation(status="applying"))
        self.assertEqual(outcome.status, "ready")
        self.assertEqual(len(store.results), len(plan.steps) - 2)
        self.assertEqual(client.records, created)  # nothing was created a second time
        self.assertNotIn(ProvisioningStatus.APPLYING, store.statuses)  # already applying: no new status revision

    def test_an_engine_that_is_down_is_retried_and_one_that_refuses_is_failed(self):
        class Down(FakeClient):
            def __init__(self, error):
                super().__init__()
                self.error = error

            def create_record(self, table, fields):
                raise self.error

        down, _, _ = executor(Down(IdempiereApiError(503, "t", "d")))[0], None, None
        self.assertEqual(down.run(operation()).code, "ENGINE_UNAVAILABLE")
        refused = executor(Down(IdempiereApiError(400, "t", "d")))[0]
        self.assertEqual((refused.run(operation()).status, refused.run(operation()).code), ("failed", "ENGINE_REJECTED"))

    def test_an_inactive_native_record_is_not_ready_yet(self):
        class Inactive(FakeClient):
            def get_record(self, table, record_id):
                return {**super().get_record(table, record_id), "IsActive": False}

        outcome = executor(Inactive())[0].run(operation())
        self.assertEqual((outcome.status, outcome.code), ("retry", "NOT_READY"))
        self.assertIn("idempiere.create_client", outcome.detail)


if __name__ == "__main__":
    unittest.main()
