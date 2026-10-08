"""An accepted provisioning command is executed by application.provisioning_worker, against real Postgres and a fake engine.

The accept path commits nothing in these suites (the Finance baseline is append-only), so the worker's own commits and rollbacks are
emulated with a savepoint: ``commit`` keeps what happened so far, ``rollback`` discards only what happened since. That keeps the
real stores, real SQL and real event outbox in play while every test still ends rolled back.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone

import psycopg

from application.provisioning_worker import run_once
from integration.idempiere_client import IdempiereApiError, IdempiereClientError
from provisioning.command_store import PostgresProvisioningCommandStore
from provisioning.execution_store import PostgresProvisioningExecutionQueue
from provisioning.native_processes import NativeProvisioningProcesses

from test_provisioning_operations import _Fixture, NOW  # noqa: F401  (NOW: the fixtures' clock)

PROCESSES = NativeProvisioningProcesses(9001, {"ZA": 9002})


class Savepointed:
    """A connection whose commit/rollback act on a savepoint, so the worker's transaction boundaries are real but nothing persists."""

    def __init__(self, connection):
        self._connection = connection
        self._connection.execute("SAVEPOINT worker")

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args, **kwargs)

    def commit(self):
        self._connection.execute("RELEASE SAVEPOINT worker")
        self._connection.execute("SAVEPOINT worker")

    def rollback(self):
        self._connection.execute("ROLLBACK TO SAVEPOINT worker")


class Engine:
    """A fake iDempiere that keeps its records outside Postgres, as the real one would, and can lose a response after acting."""

    def __init__(self):
        self.records, self.next, self.processes, self.script = {}, 1000, [], []

    def tables(self, table):
        return {record_id: fields for (name, record_id), fields in self.records.items() if name == table}

    def create_record(self, table, fields):
        step = self.script.pop(0) if self.script else None
        if step == "down":
            raise IdempiereClientError("connection refused")
        if step == "reject":
            raise IdempiereApiError(400, "Bad Request", "tenant data that must not be stored")
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        if step == "lose-response":
            raise IdempiereClientError("connection reset after the engine acted")
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def query(self, table, conditions, select):
        wanted = {condition.column: condition.value for condition in conditions}
        return [{f"{table}_ID": record_id} for record_id, fields in self.tables(table).items()
                if all(fields.get(column) == value for column, value in wanted.items())]

    def update_record(self, table, record_id, fields):
        self.records[(table, record_id)].update(fields)

    def execute_process(self, process_id, parameters):
        self.processes.append(process_id)
        return {"process_id": process_id, "ok": True}


class ProvisioningExecutionTests(_Fixture):
    def setUp(self):
        super().setUp()
        self.engine = Engine()
        self.operation = self.post()[1]["operation_id"]
        self.provisioning_id = self._one("SELECT provisioning_id FROM baobab.erp_provisioning_command_entity WHERE operation_id = %s",
                                         (self.operation,))
        self.engine_instance = self.body["engine_instance"]["engine_instance_id"] if "engine_instance" in self.body else None
        self.worker = Savepointed(self.connection)

    def _one(self, sql, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        return row[0] if row else None

    def run_worker(self, *, engine="default", processes="default", limit=10):
        engine = self.engine if engine == "default" else engine
        return run_once(self.worker, (lambda engine_instance_id: engine), PROCESSES if processes == "default" else processes,
                        limit=limit, now=lambda: NOW)

    def make_due(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_operation SET next_attempt_at = now() - interval '1 second' "
                           "WHERE provisioning_id = %s", (self.provisioning_id,))

    def row(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT status, attempts, outcome_code, last_error, next_attempt_at FROM baobab.erp_provisioning_operation "
                           "WHERE provisioning_id = %s", (self.provisioning_id,))
            return cursor.fetchone()

    def command(self):
        return PostgresProvisioningCommandStore(self.connection).get(self.tenant, self.operation)

    def states_announced(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT payload_json->>'state' FROM baobab.event_outbox WHERE ce_subject = %s "
                           "ORDER BY (payload_json->>'revision')::int", (f"provisioning:{self.operation}",))
            return [row[0] for row in cursor.fetchall()]

    def tenant_mapping(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT ad_client_id, ad_org_id, engine_instance_id FROM baobab.tenant_mapping "
                           "WHERE tenant_id = %s AND entity_id = %s AND status = 'active'", (self.tenant, self.entity))
            return cursor.fetchone()

    # -- the whole path ----------------------------------------------------------------------------------------------------------
    def test_an_accepted_command_is_provisioned_and_the_legal_entity_becomes_resolvable(self):
        self.assertEqual((self.command().state, self.row()[0]), ("accepted", "planned"))
        report = self.run_worker()
        self.assertEqual((report["pass"], report["codes"]), ({"ready": 1}, {"READY": 1}))
        self.assertEqual((self.row()[0], self.command().state), ("ready", "active"))
        (client_id, _), = [(i, f) for i, f in self.engine.tables("AD_Client").items()]
        self.assertEqual(self.tenant_mapping(), (client_id, 0, self._one(
            "SELECT desired_state->>'engine_instance_id' FROM baobab.erp_provisioning_operation WHERE provisioning_id = %s",
            (self.provisioning_id,))))
        self.assertEqual(sorted(self.engine.processes), [9001, 9002])
        self.assertEqual(self.states_announced()[0], "accepted")
        self.assertEqual(self.states_announced()[-1], "active")  # every committed revision was announced, as with any status change

    def test_running_again_provisions_nothing_twice(self):
        self.run_worker()
        before = dict(self.engine.records)
        report = self.run_worker()
        self.assertEqual(report["pass"], {})
        self.assertEqual(self.engine.records, before)
        self.assertEqual(self.row()[1], 1)

    # -- an uncertain outcome is not repeated --------------------------------------------------------------------------------------
    def test_a_response_lost_after_the_engine_acted_is_adopted_not_repeated(self):
        self.engine.script = ["lose-response"]  # the AD_Client is created; this side never learns its id
        first = self.run_worker()
        self.assertEqual(first["codes"], {"ENGINE_UNAVAILABLE": 1})
        self.assertEqual((self.row()[0], self.row()[2]), ("applying", "ENGINE_UNAVAILABLE"))
        self.assertEqual(len(self.engine.tables("AD_Client")), 1)
        self.make_due()
        second = self.run_worker()
        self.assertEqual(second["codes"], {"READY": 1})
        self.assertEqual(len(self.engine.tables("AD_Client")), 1)  # still one: it was found by its marker and adopted
        self.assertEqual(self.command().state, "active")

    def test_an_engine_that_is_down_is_retried_with_backoff_until_it_is_back(self):
        self.engine.script = ["down", "down"]
        self.assertEqual(self.run_worker()["codes"], {"ENGINE_UNAVAILABLE": 1})
        status, attempts, code, _, next_attempt = self.row()
        self.assertEqual((status, attempts, code), ("applying", 1, "ENGINE_UNAVAILABLE"))
        self.assertGreater(next_attempt, datetime.now(timezone.utc))
        self.assertEqual(self.run_worker()["pass"], {})  # not due yet: nothing is retried early
        self.make_due()
        self.run_worker()
        self.assertEqual(self.row()[1], 2)
        self.make_due()
        self.assertEqual(self.run_worker()["codes"], {"READY": 1})
        self.assertEqual((len(self.engine.tables("AD_Client")), self.command().state), (1, "active"))

    # -- what is not started ----------------------------------------------------------------------------------------------------
    def test_no_provisioner_session_blocks_the_operation_without_touching_the_engine(self):
        report = self.run_worker(engine=None)
        self.assertEqual(report["codes"], {"ENGINE_UNCONFIGURED": 1})
        status, _, code, _, next_attempt = self.row()
        self.assertEqual((status, code, self.command().state), ("planned", "ENGINE_UNCONFIGURED", "accepted"))
        self.assertGreater(next_attempt, datetime.now(timezone.utc) + timedelta(minutes=10))

    def test_a_missing_process_blocks_before_any_client_is_created(self):
        for processes in (None, NativeProvisioningProcesses(9001, {"UG": 1})):
            with self.subTest(processes=processes):
                self.make_due()
                self.assertEqual(self.run_worker(processes=processes)["codes"], {"PROCESS_UNCONFIGURED": 1})
                self.assertEqual(self.engine.records, {})  # no AD_Client waiting for accounting that cannot be configured
        self.assertEqual(self.command().state, "accepted")

    def test_state_that_is_not_what_was_approved_is_failed_and_the_engine_untouched(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_operation SET desired_state = jsonb_set(desired_state, '{legal_name}', "
                           "'\"Someone Else Ltd\"') WHERE provisioning_id = %s", (self.provisioning_id,))
        self.assertEqual(self.run_worker()["codes"], {"STATE_DRIFT": 1})
        self.assertEqual((self.engine.records, self.row()[0], self.command().state), ({}, "failed", "failed"))

    def test_a_cancelled_command_is_not_executed(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_command SET state = 'cancelled' WHERE operation_id = %s", (self.operation,))
        self.assertEqual(self.run_worker()["pass"], {})
        self.assertEqual(self.engine.records, {})

    # -- failure ------------------------------------------------------------------------------------------------------------------
    def test_a_refusal_fails_the_command_with_the_fixed_code_and_nothing_of_the_engine_message(self):
        self.engine.script = ["reject"]
        self.assertEqual(self.run_worker()["codes"], {"ENGINE_REJECTED": 1})
        command = self.command()
        self.assertEqual((command.state, command.failure_code), ("failed", "ERP_PROVISIONING_FAILED"))
        stored = json.dumps(self.row(), default=str) + json.dumps(self.states_announced())
        self.assertNotIn("tenant data", stored)
        self.assertEqual(self.run_worker()["pass"], {})  # a failed command is not retried by the worker

    def test_the_attempt_budget_ends_in_a_failure(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_operation SET attempts = 23 WHERE provisioning_id = %s", (self.provisioning_id,))
        self.engine.script = ["down"]
        self.assertEqual(self.run_worker()["codes"], {"ATTEMPTS_EXHAUSTED": 1})
        self.assertEqual(self.command().state, "failed")

    def test_waiting_for_an_operator_does_not_spend_the_retry_budget(self):
        for _ in range(3):
            self.make_due()
            self.assertEqual(self.run_worker(engine=None)["codes"], {"ENGINE_UNCONFIGURED": 1})
        self.assertEqual(self.row()[1], 0)  # three blocked passes, none counted
        self.engine.script = ["down"]
        self.make_due()
        self.assertEqual(self.run_worker()["codes"], {"ENGINE_UNAVAILABLE": 1})
        self.assertEqual(self.row()[1], 1)

    def test_a_command_cancelled_after_the_operation_was_found_due_is_not_started(self):
        queue = PostgresProvisioningExecutionQueue(self.worker)
        self.assertEqual(queue.due(10), [self.provisioning_id])
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_command SET state = 'cancelled' WHERE operation_id = %s", (self.operation,))
        self.assertIsNone(queue.begin(self.provisioning_id))
        self.assertEqual(self.row()[1], 0)

    def test_a_block_that_outlives_its_horizon_ends_in_a_failure(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_operation SET created_at = %s WHERE provisioning_id = %s",
                           (NOW - timedelta(days=4), self.provisioning_id))
        self.assertEqual(self.run_worker(engine=None)["codes"], {"BLOCKED_HORIZON_EXCEEDED": 1})
        self.assertEqual(self.command().state, "failed")

    # -- exclusion and the tenant mapping ----------------------------------------------------------------------------------------
    def test_an_operation_another_worker_holds_is_left_alone(self):
        other = psycopg.connect(_dsn())
        self.addCleanup(other.close)
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 19))", (self.provisioning_id,))
        # the accepted command is not committed, so the other session cannot see it: the lock is taken by key all the same
        report = self.run_worker()
        self.assertEqual((report["contended"], report["pass"]), (1, {}))
        self.assertEqual(self.engine.records, {})

    def test_a_mapping_that_already_exists_for_another_native_client_is_a_conflict(self):
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, engine_instance_id) "
                           "VALUES (%s, %s, 424242, 0, 'ei_someone_else')", (self.tenant, self.entity))
        self.assertEqual(self.run_worker()["codes"], {"TENANT_MAPPING_CONFLICT": 1})
        self.assertEqual(self.command().state, "failed")
        self.assertEqual(self.tenant_mapping(), (424242, 0, "ei_someone_else"))  # the existing mapping is not overwritten

    def test_a_mapping_written_by_an_attempt_that_died_is_confirmed_not_a_conflict(self):
        self.run_worker()
        # the step record was lost after the mapping was written: PERSIST_MAPPING runs again with identical values
        with self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM baobab.erp_provisioning_step WHERE provisioning_id = %s AND step_key LIKE '%%:mapping'",
                           (self.provisioning_id,))
            cursor.execute("UPDATE baobab.erp_provisioning_operation SET status = 'reconciling' WHERE provisioning_id = %s",
                           (self.provisioning_id,))
        before = self.tenant_mapping()
        self.make_due()
        self.assertEqual(self.run_worker()["codes"], {"READY": 1})
        self.assertEqual(self.tenant_mapping(), before)


def _dsn():
    import os
    return os.environ["DATABASE_URL"]


if __name__ == "__main__":
    unittest.main()
