"""The order-consequence read model on real Postgres: the order-to-cash steps maintain it in their own transaction and the
boundary read serves it, tenant-scoped. Nothing commits; every test rolls back."""
import sys
import unittest
import uuid
from pathlib import Path

import psycopg

from application.boundary import get_order_consequence
from mapping.postgres_store import PostgresCanonicalMappingStore
from order_to_cash import service
from order_to_cash.consequence_store import PostgresOrderConsequenceStore
from order_to_cash.model import OrderLine, TenantScope
from outbox.postgres_store import PostgresOutboxStore

# CI discovers this directory with only modules/ on the path; the fakes live with the unit tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from _postgres import connect  # noqa: E402
from test_order_to_cash_service import PROCESS_IDS, FakeIdempiereClient  # noqa: E402


class OrderConsequenceTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.addCleanup(self._rollback)
        self.tenant = f"tn_{uuid.uuid4().hex[:16]}"
        self.other = f"tn_{uuid.uuid4().hex[:16]}"
        self.scope = TenantScope(tenant_id=self.tenant, legal_entity_id="ZURIBEANS-ZA", ad_client_id=1001, ad_org_id=1)
        self.order = str(uuid.uuid4())
        self.idempiere = FakeIdempiereClient()
        self.mappings = PostgresCanonicalMappingStore(self.connection)
        self.outbox = PostgresOutboxStore(self.connection)
        self.store = PostgresOrderConsequenceStore(self.connection)

    def _rollback(self):
        self.connection.rollback()
        self.connection.close()

    def read(self, tenant=None, order=None):
        return get_order_consequence(tenant_id=tenant or self.tenant, argument=order or self.order,
                                     connection=self.connection, correlation_id=str(uuid.uuid4()), trace_id=None)

    def create_order(self, **kw):
        return service.create_sales_order(
            scope=self.scope, commerce_order_canonical_id=self.order, business_partner_native_id=1,
            document_currency="ZAR", lines=(OrderLine("p", "1", "1.00"),), idempiere=self.idempiere,
            mappings=self.mappings, consequences=self.store, **kw)

    def step(self, fn, **kw):
        return fn(scope=self.scope, idempiere=self.idempiere, mappings=self.mappings, consequences=self.store, **kw)

    def test_the_whole_sequence_moves_the_read_model_and_the_read_serves_it(self):
        self.create_order(order_version=3)
        status, body = self.read()
        self.assertEqual((status, body["status"], body["accounting_status"], body["inventory_status"], body["revision"]),
                         (200, "accepted", "pending", "pending", 1))
        self.assertEqual((body["order_version"], body["legal_entity_id"]), (3, "ZURIBEANS-ZA"))
        self.assertRegex(body["erp_order_id"], r"^erp_[a-z0-9]+$")
        self.assertEqual(body["erp_order_id"], self.mappings.erp_resource_id(self.tenant, "CommerceOrder", self.order))

        self.step(service.complete_sales_order, commerce_order_canonical_id=self.order, correlation_id="c",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        self.assertEqual(self.read()[1]["status"], "processing")

        shipment = str(uuid.uuid4())
        self.step(service.create_shipment, shipment_canonical_id=shipment, commerce_order_canonical_id=self.order)
        self.step(service.complete_shipment, shipment_canonical_id=shipment, correlation_id="c",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        self.assertEqual(self.read()[1]["inventory_status"], "fulfilled")
        self.assertEqual(self.read()[1]["status"], "processing")

        invoice = self.step(service.create_customer_invoice, commerce_order_canonical_id=self.order)
        self.step(service.post_customer_invoice, invoice_canonical_id=invoice.canonical_id, correlation_id="c",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        _, body = self.read()
        self.assertEqual((body["status"], body["accounting_status"], body["inventory_status"]),
                         ("posted", "posted", "fulfilled"))
        self.assertEqual(body["revision"], 4)
        self.assertEqual(body["invoice_id"], self.mappings.erp_resource_id(self.tenant, "CustomerInvoice", invoice.canonical_id))
        self.assertNotIn("C_", str(body), "no native table or id reaches the contract")

    def outbox_rows(self, connection=None):
        with (connection or self.connection).cursor() as cursor:
            cursor.execute("SELECT event_type, status, envelope_format, payload_json->>'revision', ce_subject, "
                           "ce_idempotency_key FROM baobab.event_outbox WHERE tenant_id = %s ORDER BY occurred_at, id",
                           (self.tenant,))
            return cursor.fetchall()

    def test_each_change_announces_the_registered_event_in_the_same_transaction(self):
        self.create_order(order_version=3, outbox=self.outbox, correlation_id="corr-1")
        shipment = str(uuid.uuid4())
        self.step(service.complete_sales_order, commerce_order_canonical_id=self.order, correlation_id="corr-1",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        self.step(service.create_shipment, shipment_canonical_id=shipment, commerce_order_canonical_id=self.order)
        self.step(service.complete_shipment, shipment_canonical_id=shipment, correlation_id="corr-1",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        invoice = self.step(service.create_customer_invoice, commerce_order_canonical_id=self.order)
        self.step(service.post_customer_invoice, invoice_canonical_id=invoice.canonical_id, correlation_id="corr-1",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        canonical = [r for r in self.outbox_rows() if r[2] == "cloudevents"]
        self.assertEqual([r[3] for r in canonical], ["1", "2", "3", "4"])
        self.assertTrue(all(r[0] == "com.baobab-platform.erp.order.consequence-changed.v1" and r[1] == "pending"
                            and r[4] == f"order:{self.order}" for r in canonical))
        self.assertEqual(canonical[3][5], f"erp-order-consequence-{self.order}-r4")
        # the legacy held rows are still recorded alongside, and are never delivered
        self.assertTrue(all(r[1] == "held" for r in self.outbox_rows() if r[2] == "legacy"))
        # nothing is visible to anyone else until the caller's transaction commits
        other = connect()
        self.addCleanup(other.close)
        self.assertEqual(self.outbox_rows(other), [])
        # and the dispatcher would pick up exactly the canonical rows
        self.assertEqual(len([r for r in self.outbox.pending(100) if r.event.subject == f"order:{self.order}"]), 4)

    def test_a_repeated_fact_announces_nothing_and_an_order_without_a_record_announces_nothing(self):
        self.create_order(order_version=1, outbox=self.outbox)
        for _ in range(2):
            self.step(service.complete_sales_order, commerce_order_canonical_id=self.order, correlation_id="c",
                      process_ids=PROCESS_IDS, outbox=self.outbox)
        self.assertEqual([r[3] for r in self.outbox_rows() if r[2] == "cloudevents"], ["1", "2"])
        self.order = str(uuid.uuid4())
        self.create_order(outbox=self.outbox)
        self.step(service.complete_sales_order, commerce_order_canonical_id=self.order, correlation_id="c",
                  process_ids=PROCESS_IDS, outbox=self.outbox)
        self.assertEqual(len([r for r in self.outbox_rows() if r[2] == "cloudevents"]), 2)

    def test_a_repeated_fact_does_not_bump_the_revision(self):
        self.create_order(order_version=1)
        for _ in range(2):
            self.step(service.complete_sales_order, commerce_order_canonical_id=self.order, correlation_id="c",
                      process_ids=PROCESS_IDS, outbox=self.outbox)
        self.assertEqual(self.read()[1]["revision"], 2)

    def test_an_order_without_a_version_has_no_record_and_reads_404(self):
        self.create_order()
        self.assertEqual(self.read()[0], 404)

    def test_the_read_is_tenant_scoped(self):
        self.create_order(order_version=1)
        status, body = self.read(tenant=self.other)
        self.assertEqual((status, body["code"]), (404, "ERP_RESOURCE_NOT_FOUND"))
        self.assertEqual(self.read(order="not-an-order")[0], 404)

    def test_a_problem_status_requires_an_exception_code(self):
        self.create_order(order_version=1)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.cursor() as cursor:
                cursor.execute("UPDATE baobab.order_consequence SET status = 'needs_review' WHERE tenant_id = %s",
                               (self.tenant,))


if __name__ == "__main__":
    unittest.main()
