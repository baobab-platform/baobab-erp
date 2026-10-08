"""The executed order path against the real Shared contracts at the pin (ERP-COMPAT-06).

Input is Shared's own ``commerce-order-placed.json`` example, byte for byte as Trade's contract shows it. It is received through
ERP's inbox store, executed by the inbox worker, and the event ERP then announces is checked against Shared's envelope and the
registered ``order-consequence-status`` schema, equals the read model the boundary serves, and survives delivery through the
outbox dispatcher. Only the engine is a stand-in (an in-process object, no network)."""
import os
import unittest
import uuid

import _shared as shared
import psycopg
from application.inbox_worker import run_once
from events.cloudevent import CloudEvent, check_consumable
from inbox.postgres_store import PostgresInboxStore
from order_to_cash.consequence_store import PostgresOrderConsequenceStore
from order_to_cash.placed_order import parse_placed_order
from outbox.postgres_store import PostgresOutboxStore
from outbox.service import dispatch_pending

ENVELOPE = shared.schema_uri("events/v1/envelope.schema.json")


class _Engine:
    def __init__(self):
        self.created = []

    def get_record(self, table, record_id):
        return {"C_UOM_ID": 1} if table == "M_Product" else {"X12DE355": "EA"}

    def query(self, table, conditions, select):
        return [{"id": rec["id"]} for rec in self.created if rec["POReference"] == conditions[0].value]

    def create_record(self, table, fields):
        self.created.append({"id": 9100 + len(self.created), **fields})
        return 9100 + len(self.created) - 1


class _Capture:
    def __init__(self):
        self.delivered = []

    def deliver(self, event):
        self.delivered.append(event)


class OrderExecutionConformanceTests(unittest.TestCase):
    def setUp(self):
        self.db = psycopg.connect(os.environ["DATABASE_URL"])
        self.tag = uuid.uuid4().hex[:10]
        wire = shared.read_json("erp/v1/examples/commerce-order-placed.json")
        wire["id"], wire["tenantid"] = str(uuid.uuid4()), f"tn_{self.tag}"
        self.wire = wire
        self.order = wire["data"]["commerce_order_id"]
        self.entity = wire["data"]["legal_entity_id"]
        self.instance = f"ei_{self.tag}"
        with self.db.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, legal_entity_id, "
                           "engine_instance_id) VALUES (%s,%s,%s,1,%s,%s)",
                           (wire["tenantid"], self.entity, int(self.tag[:6], 16) + 200000, self.entity, self.instance))
            for kind, canonical, native in (("business_partner", wire["data"]["customer_id"], 11),
                                            ("product", wire["data"]["lines"][0]["sku_id"], 22)):
                cursor.execute("INSERT INTO baobab.erp_master_data_mapping (engine_instance_id, legal_entity_id, resource_kind, "
                               "canonical_id, native_id, desired_digest, source_version) VALUES (%s,%s,%s,%s,%s,'d','1')",
                               (self.instance, self.entity, kind, canonical, native))
        self.db.commit()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.db.rollback()
        tenant = self.wire["tenantid"]
        with self.db.cursor() as cursor:
            for table in ("order_execution", "order_consequence", "event_outbox", "event_inbox", "tenant_mapping"):
                cursor.execute(f"DELETE FROM baobab.{table} WHERE tenant_id = %s", (tenant,))
            cursor.execute("DELETE FROM baobab.erp_master_data_mapping WHERE engine_instance_id = %s", (self.instance,))
        self.db.commit()
        self.db.close()

    def test_the_shared_example_executes_and_its_outcome_event_conforms_and_is_delivered(self):
        self.assertEqual(shared.errors(ENVELOPE, self.wire), [])
        self.assertEqual(shared.errors(self.wire["dataschema"], self.wire["data"]), [])
        parse_placed_order(self.wire["data"])  # the executor's reader accepts everything the contract example carries
        event = check_consumable(CloudEvent.from_wire(self.wire))
        PostgresInboxStore(self.db).record_received(event, __import__("json").dumps(event.data, sort_keys=True))
        engine = _Engine()

        report = run_once(self.db, lambda _ad_client, _ad_org: engine, worker_id="conformance", limit=5)

        self.assertEqual(report["codes"], {"EXECUTED": 1})
        self.assertEqual(len(engine.created), 1)
        sink = _Capture()
        summary = dispatch_pending(PostgresOutboxStore(self.db), sink, types=("com.baobab-platform.erp.order.consequence-changed.v1",))
        self.db.commit()
        self.assertGreaterEqual(summary.delivered, 1)  # a shared test database may hold other tenants' pending events
        [announced] = [e for e in sink.delivered if e.tenantid == self.wire["tenantid"]]
        wire = announced.to_wire()
        self.assertEqual(shared.errors(ENVELOPE, wire), [])
        self.assertEqual(shared.errors(announced.dataschema, announced.data), [])
        self.assertEqual(announced.tenantid, self.wire["tenantid"])
        self.assertEqual(announced.data["commerce_order_id"], self.order)
        record = PostgresOrderConsequenceStore(self.db).get(self.wire["tenantid"], self.order)
        self.db.commit()
        self.assertEqual(announced.data, record.to_contract())  # the event and GET /order-consequences are one record
        self.assertEqual((announced.data["status"], announced.data["revision"]), ("accepted", 1))


if __name__ == "__main__":
    unittest.main()
