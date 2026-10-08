"""invoice.changed and payment.accounting-changed against the pinned Shared contracts (ERP-CAP-05/08).

The events are produced by ERP's own service functions from facts read back from a fake engine, then validated against the envelope and
the payload schema each names. Each change is announced once; what the engine does not report is never invented."""
import unittest
import uuid
from datetime import datetime

import _shared as shared
from events import registry
from order_to_cash import accounting_outcomes as rules
from order_to_cash import service
from order_to_cash.model import TenantScope

ENVELOPE = shared.schema_uri("events/v1/envelope.schema.json")
TENANT = "tn_01k4m7x9q2v6c8r3d5f1h0j4"
ORDER = str(uuid.uuid4())
INVOICE = str(uuid.uuid4())
PAYMENT = str(uuid.uuid4())


class Engine:
    def __init__(self):
        self.records = {
            ("C_Currency", 1): {"ISO_Code": "KES", "StdPrecision": 2},
            ("C_Invoice", 11): {"DocumentNo": "INV-1001", "GrandTotal": "1160", "C_Currency_ID": 1, "DocStatus": {"id": "CO"},
                                "IsPaid": False},
            ("C_Payment", 21): {"PayAmt": "1160", "C_Currency_ID": 1, "DocStatus": {"id": "CO"}, "IsAllocated": False},
        }

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def execute_process(self, process_id, parameters):
        return {}


class Mappings:
    def find_native(self, tenant_id, canonical_type, canonical_id):
        from mapping.model import NativeRecordRef
        return {INVOICE: NativeRecordRef("C_Invoice", 11), PAYMENT: NativeRecordRef("C_Payment", 21)}.get(canonical_id)

    def erp_resource_id(self, tenant_id, canonical_type, canonical_id):
        return {INVOICE: "erp_inv0000000001", PAYMENT: "erp_pay0000000001"}.get(canonical_id)


class Links:
    def order_of_document(self, tenant_id, document_type, document_id):
        return ORDER if document_id == INVOICE else None

    def record_fact(self, **kwargs):
        return None


class Outbox:
    def __init__(self):
        self.events = []

    def record(self, envelope):
        pass

    def record_event(self, event):
        self.events.append(event)


class Outcomes:
    def __init__(self):
        self.rows = {}

    def advance(self, *, tenant_id, document_type, document_id, status, detail, now):
        key = (tenant_id, document_type, document_id)
        row = self.rows.get(key)
        if row is None:
            self.rows[key] = (1, status, detail, now)
            return rules.Advanced(1, now, True)
        if row[1] == status and row[2] == detail:
            return rules.Advanced(row[0], row[3], False)
        self.rows[key] = (row[0] + 1, status, detail, row[3])
        return rules.Advanced(row[0] + 1, row[3], True)


IDS = service.ProcessIds(1, 2, 3, 4, 5)
SCOPE = TenantScope(tenant_id=TENANT, legal_entity_id="ZURIBEANS", ad_client_id=1000000, ad_org_id=1000001)


class AccountingOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.outbox, self.outcomes = Engine(), Outbox(), Outcomes()

    def post(self):
        service.post_customer_invoice(scope=SCOPE, invoice_canonical_id=INVOICE, correlation_id="", process_ids=IDS,
                                      idempiere=self.engine, mappings=Mappings(), outbox=self.outbox, consequences=Links(),
                                      outcomes=self.outcomes)

    def complete(self):
        service.complete_payment(scope=SCOPE, payment_canonical_id=PAYMENT, correlation_id="", process_ids=IDS,
                                 idempiere=self.engine, mappings=Mappings(), outbox=self.outbox, outcomes=self.outcomes)

    def allocate(self, amount):
        service.allocate_payment(scope=SCOPE, payment_canonical_id=PAYMENT, invoice_canonical_id=INVOICE, amount=amount,
                                 correlation_id="", process_ids=IDS, idempiere=self.engine, mappings=Mappings(),
                                 outbox=self.outbox, consequences=Links(), outcomes=self.outcomes)

    def validate(self, event, type_):
        wire = event.to_wire()
        self.assertEqual(wire["type"], type_)
        self.assertEqual(shared.errors(ENVELOPE, wire), [])
        self.assertEqual(shared.errors(wire["dataschema"], wire["data"]), [])
        self.assertEqual(wire["dataschema"], registry.dataschema_for(type_))

    def test_a_posted_invoice_is_announced_once_with_observed_facts(self):
        self.post()
        self.post()  # a retried request
        self.assertEqual(len(self.outbox.events), 1)
        event = self.outbox.events[0]
        self.validate(event, rules.INVOICE_EVENT)
        self.assertEqual(event.data["status"], "posted")
        self.assertEqual(event.data["invoice_number"], "INV-1001")
        self.assertEqual(event.data["total"], {"amount": "1160.00", "currency": "KES"})
        self.assertEqual(event.data["commerce_order_id"], ORDER)
        self.assertEqual(event.data["revision"], 1)
        self.assertNotIn("outstanding", event.data)
        self.assertNotIn("due_on", event.data)

    def test_a_completed_payment_is_announced_posted(self):
        self.complete()
        event, = self.outbox.events
        self.validate(event, rules.PAYMENT_EVENT)
        self.assertEqual((event.data["status"], event.data["revision"]), ("posted", 1))
        self.assertEqual(event.data["erp_payment_id"], "erp_pay0000000001")
        self.assertNotIn("invoice_id", event.data)

    def test_a_full_allocation_announces_the_payment_allocated_and_the_invoice_paid(self):
        self.post()
        self.complete()
        self.engine.records[("C_Invoice", 11)]["IsPaid"] = True
        self.engine.records[("C_Payment", 21)]["IsAllocated"] = True
        self.allocate("1160")
        by_type = {}
        for event in self.outbox.events:
            by_type.setdefault(event.type, []).append(event)
        payments, invoices = by_type[rules.PAYMENT_EVENT], by_type[rules.INVOICE_EVENT]
        self.assertEqual([e.data["status"] for e in payments], ["posted", "allocated"])
        self.assertEqual([e.data["revision"] for e in payments], [1, 2])
        self.assertEqual(payments[1].data["invoice_id"], "erp_inv0000000001")
        self.assertEqual([e.data["status"] for e in invoices], ["posted", "paid"])
        for event in self.outbox.events:
            self.validate(event, event.type)

    def test_a_partial_allocation_is_partial_on_both_documents(self):
        self.post()
        self.complete()
        self.allocate("400")
        self.assertEqual(self.outbox.events[-2].data["status"], "partially_allocated")
        self.assertEqual(self.outbox.events[-1].data["status"], "partially_paid")

    def test_a_payment_split_across_invoices_is_allocated_when_the_engine_says_so_not_by_the_last_request(self):
        self.complete()
        self.allocate("60")
        self.engine.records[("C_Payment", 21)]["IsAllocated"] = True  # the second request completes the allocation
        self.allocate("40")
        self.assertEqual([e.data["status"] for e in self.outbox.events if e.type == rules.PAYMENT_EVENT],
                         ["posted", "partially_allocated", "allocated"])

    def test_event_identity_is_a_function_of_document_and_revision(self):
        self.post()
        first = self.outbox.events[0]
        again = rules.invoice_changed_event(
            tenant_id=TENANT, legal_entity_id="ZURIBEANS", invoice_id="erp_inv0000000001", commerce_order_id=ORDER,
            facts=rules.read_invoice(self.engine, 11), status="posted", issued_at=datetime.fromisoformat(first.data["issued_at"].replace("Z", "+00:00")),
            revision=1, now=datetime.now().astimezone(), correlation_id=None)
        self.assertEqual(again.id, first.id)
        self.assertEqual(again.idempotencykey, first.idempotencykey)

    def test_nothing_is_announced_for_what_the_engine_did_not_complete(self):
        self.engine.records[("C_Invoice", 11)]["DocStatus"] = {"id": "DR"}
        self.engine.records[("C_Payment", 21)]["DocStatus"] = {"id": "DR"}
        self.post()
        self.complete()
        self.assertEqual(self.outbox.events, [])

    def test_an_invoice_with_no_order_link_is_not_announced(self):
        class NoLinks(Links):
            def order_of_document(self, *a):
                return None
        service.post_customer_invoice(scope=SCOPE, invoice_canonical_id=INVOICE, correlation_id="", process_ids=IDS,
                                      idempiere=self.engine, mappings=Mappings(), outbox=self.outbox, consequences=NoLinks(),
                                      outcomes=self.outcomes)
        self.assertEqual(self.outbox.events, [])

    def test_a_missing_currency_or_number_invents_nothing(self):
        del self.engine.records[("C_Invoice", 11)]["DocumentNo"]
        self.post()
        self.assertEqual(self.outbox.events, [])
