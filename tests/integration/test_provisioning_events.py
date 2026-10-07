"""A provisioning command announces every committed revision as provisioning.changed, in the same transaction (FB-04b).

Handler-level against real Postgres like test_provisioning_operations: nothing is committed, every test rolls back. The status
path goes through PostgresProvisioningStore.set_status with commits suppressed, so it is the real code under a test transaction."""
import json
import unittest
import uuid

from events.cloudevent import CloudEvent
from provisioning import command_events
from provisioning.command_store import PostgresProvisioningCommandStore
from provisioning.model import ProvisioningStatus
from provisioning.store import PostgresProvisioningStore

from test_provisioning_operations import _Fixture


class _NoCommit:
    """The test's connection with commit() suppressed, so code that commits its own unit of work stays inside the test's transaction."""

    def __init__(self, connection):
        self._connection = connection

    def cursor(self, *args, **kwargs):
        return self._connection.cursor(*args, **kwargs)

    def commit(self):
        pass

    def rollback(self):
        self._connection.rollback()


class ProvisioningEventTests(_Fixture):
    def events_of(self, operation_id):
        with self.connection.cursor() as cursor:
            cursor.execute("""SELECT event_id::text, payload_json, status, ce_idempotency_key, ce_subject, ce_correlation_id::text
                                FROM baobab.event_outbox WHERE event_type = %s AND ce_subject = %s ORDER BY (payload_json->>'revision')::int""",
                           (command_events.EVENT_TYPE, f"provisioning:{operation_id}"))
            return cursor.fetchall()

    def provisioning_id(self, operation_id):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT provisioning_id FROM baobab.erp_provisioning_command_entity WHERE operation_id = %s", (operation_id,))
            return cursor.fetchone()[0]

    def store(self):
        return PostgresProvisioningStore(_NoCommit(self.connection))

    def test_accepting_a_command_announces_revision_one_in_the_same_transaction(self):
        operation = self.post()[1]["operation_id"]
        (event_id, data, status, key, subject, _), = self.events_of(operation)
        self.assertEqual((event_id, key, status), (command_events.event_id(operation, 1),
                                                   command_events.idempotency_key(operation, 1), "pending"))
        self.assertEqual((data["operation_id"], data["state"], data["revision"], data["legal_entity_ids"]),
                         (operation, "accepted", 1, [self.entity]))
        self.connection.rollback()  # the command and its event are one unit of work
        self.assertEqual(self.events_of(operation), [])
        self.assertIsNone(PostgresProvisioningCommandStore(self.connection).get(self.tenant, operation))

    def test_the_event_carries_exactly_what_the_operation_read_answers(self):
        operation = self.post()[1]["operation_id"]
        (_, data, *_), = self.events_of(operation)
        status, read = self.get(operation)
        self.assertEqual((status, data), (200, read))

    def test_a_replay_of_the_same_request_announces_nothing_new(self):
        operation = self.post()[1]["operation_id"]
        self.post()
        self.assertEqual(len(self.events_of(operation)), 1)

    def test_a_refused_request_announces_nothing(self):
        self.post(self.request(requested_countries=["ZA", "UG"]), key=self.fresh_key())
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM baobab.event_outbox WHERE event_type = %s AND tenant_id = %s",
                           (command_events.EVENT_TYPE, self.tenant))
            before = cursor.fetchone()[0]
        self.post(self.request(finance_baselines=[]), key=self.fresh_key())
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM baobab.event_outbox WHERE event_type = %s AND tenant_id = %s",
                           (command_events.EVENT_TYPE, self.tenant))
            self.assertEqual(cursor.fetchone()[0], before)

    def test_an_entitys_status_change_advances_the_command_and_announces_each_revision(self):
        operation = self.post()[1]["operation_id"]
        provisioning = self.provisioning_id(operation)
        store = self.store()
        for status, state, revision in ((ProvisioningStatus.APPLYING, "provisioning", 2),
                                        (ProvisioningStatus.RECONCILING, "reconciling", 3),
                                        (ProvisioningStatus.READY, "active", 4)):
            store.set_status(provisioning, status)
            with self.subTest(status):
                record = PostgresProvisioningCommandStore(self.connection).get(self.tenant, operation)
                self.assertEqual((record.state, record.revision, record.failure_code), (state, revision, None))
                self.assertEqual(self.events_of(operation)[-1][0], command_events.event_id(operation, revision))
        self.assertEqual([row[1]["state"] for row in self.events_of(operation)], ["accepted", "provisioning", "reconciling", "active"])
        self.assertEqual([row[1]["revision"] for row in self.events_of(operation)], [1, 2, 3, 4])

    def test_a_status_that_does_not_change_the_commands_state_announces_nothing(self):
        operation = self.post()[1]["operation_id"]
        provisioning = self.provisioning_id(operation)
        store = self.store()
        store.set_status(provisioning, ProvisioningStatus.APPLYING)
        store.set_status(provisioning, ProvisioningStatus.APPLYING)
        self.assertEqual(len(self.events_of(operation)), 2)

    def test_failure_carries_a_fixed_code_and_never_the_entitys_error(self):
        operation = self.post()[1]["operation_id"]
        provisioning = self.provisioning_id(operation)
        self.store().set_status(provisioning, ProvisioningStatus.FAILED, "psycopg connection refused at 10.0.0.7 password=hunter2")
        record = PostgresProvisioningCommandStore(self.connection).get(self.tenant, operation)
        self.assertEqual((record.state, record.failure_code), ("failed", "ERP_PROVISIONING_FAILED"))
        (_, data, *_) = self.events_of(operation)[-1]
        self.assertEqual(data["failure_code"], "ERP_PROVISIONING_FAILED")
        self.assertNotIn("hunter2", json.dumps(self.events_of(operation)))
        # A retry that succeeds clears the failure and is announced as a new revision.
        self.store().set_status(provisioning, ProvisioningStatus.APPLYING)
        record = PostgresProvisioningCommandStore(self.connection).get(self.tenant, operation)
        self.assertEqual((record.state, record.failure_code, record.revision), ("provisioning", None, 3))
        self.assertNotIn("failure_code", self.events_of(operation)[-1][1])

    def test_a_rolled_back_status_change_is_never_announced(self):
        operation = self.post()[1]["operation_id"]
        provisioning = self.provisioning_id(operation)
        with self.connection.cursor() as cursor:
            cursor.execute("SAVEPOINT before_status")
        self.store().set_status(provisioning, ProvisioningStatus.APPLYING)
        self.assertEqual(len(self.events_of(operation)), 2)
        with self.connection.cursor() as cursor:
            cursor.execute("ROLLBACK TO SAVEPOINT before_status")
        self.assertEqual(len(self.events_of(operation)), 1)
        record = PostgresProvisioningCommandStore(self.connection).get(self.tenant, operation)
        self.assertEqual((record.state, record.revision), ("accepted", 1))

    def test_a_cancelled_command_stays_cancelled(self):
        operation = self.post()[1]["operation_id"]
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE baobab.erp_provisioning_command SET state = 'cancelled', revision = 2 WHERE operation_id = %s", (operation,))
        self.assertIsNone(PostgresProvisioningCommandStore(self.connection).advance(operation, "active"))
        self.assertEqual(len(self.events_of(operation)), 1)

    def test_a_failure_code_accompanies_the_failed_state_and_nothing_else(self):
        operation = self.post()[1]["operation_id"]
        commands = PostgresProvisioningCommandStore(self.connection)
        with self.assertRaises(ValueError):
            commands.advance(operation, "failed")
        with self.assertRaises(ValueError):
            commands.advance(operation, "active", "ERP_PROVISIONING_FAILED")

    def test_a_provisioning_record_that_belongs_to_no_command_is_left_alone(self):
        solo = f"solo-{uuid.uuid4().hex[:8]}"
        with self.connection.cursor() as cursor:
            cursor.execute("""INSERT INTO baobab.erp_provisioning_operation (provisioning_id, idempotency_key, desired_state, status)
                              VALUES (%s, %s, '{}'::jsonb, 'planned')""", (solo, solo))
        self.store().set_status(solo, ProvisioningStatus.APPLYING)
        self.assertIsNone(PostgresProvisioningCommandStore(self.connection).project(solo))

    def test_every_event_is_a_valid_deliverable_canonical_event(self):
        operation = self.post()[1]["operation_id"]
        self.store().set_status(self.provisioning_id(operation), ProvisioningStatus.APPLYING)
        for event_id, data, *_ in self.events_of(operation):
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT event_type FROM baobab.event_outbox WHERE event_id = %s::uuid", (event_id,))
                self.assertEqual(cursor.fetchone()[0], command_events.EVENT_TYPE)
            self.assertEqual(uuid.UUID(event_id).version, 5)


if __name__ == "__main__":
    unittest.main()
