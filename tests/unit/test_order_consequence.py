import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from order_to_cash import service
from order_to_cash.consequence import Fact, Facts, OrderConsequence, derive
from order_to_cash.model import OrderLine, TenantScope

from test_order_to_cash_service import PROCESS_IDS, FakeIdempiereClient, FakeMappingStore, FakeOutboxStore

SCOPE = TenantScope(tenant_id="tn_zuri", legal_entity_id="ZURIBEANS-ZA", ad_client_id=1001, ad_org_id=1)
ORDER = "11111111-1111-4111-8111-111111111111"


class DerivationTests(unittest.TestCase):
    def test_nothing_observed_means_accepted_and_pending(self):
        derived = derive(Facts())
        self.assertEqual((derived.status, derived.accounting_status, derived.inventory_status),
                         ("accepted", "pending", "pending"))

    def test_each_observed_fact_establishes_only_its_own_consequence(self):
        completed = derive(Facts(order_completed=True))
        self.assertEqual((completed.status, completed.accounting_status, completed.inventory_status),
                         ("processing", "pending", "pending"))
        shipped = derive(Facts(order_completed=True, shipment_completed=True))
        self.assertEqual((shipped.status, shipped.accounting_status, shipped.inventory_status),
                         ("processing", "pending", "fulfilled"))
        invoiced = derive(Facts(order_completed=True, invoice_posted=True))
        self.assertEqual((invoiced.status, invoiced.accounting_status, invoiced.inventory_status),
                         ("processing", "posted", "pending"))

    def test_posted_needs_both_accounting_and_inventory(self):
        done = derive(Facts(True, True, True))
        self.assertEqual((done.status, done.accounting_status, done.inventory_status), ("posted", "posted", "fulfilled"))

    def test_the_outcomes_nothing_observes_are_never_inferred(self):
        for facts in (Facts(), Facts(True), Facts(True, True), Facts(True, False, True), Facts(True, True, True)):
            derived = derive(facts)
            self.assertNotIn(derived.status, ("needs_review", "rejected", "compensated"))
            self.assertNotIn(derived.accounting_status, ("needs_review", "failed", "not_applicable"))
            self.assertNotIn(derived.inventory_status, ("allocated", "backordered", "needs_review", "failed", "not_applicable"))

    def test_the_contract_document_omits_what_is_absent(self):
        record = OrderConsequence("tn_zuri", ORDER, "ZURIBEANS-ZA", 2, "erp_abc12345", "processing", "pending", "pending", 3,
                                  datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))
        body = record.to_contract()
        self.assertNotIn("invoice_id", body)
        self.assertNotIn("exception_code", body)
        self.assertNotIn("tenant_id", body)
        self.assertEqual(body["updated_at"], "2026-10-02T09:00:00Z")


class RecordingConsequences:
    """Records the calls and answers like the Postgres store: a repeated fact reports changed=False."""

    def __init__(self):
        self.calls = []
        self.docs = {}
        self.facts = set()
        self.revision = 1

    def _record(self, status="accepted"):
        return OrderConsequence("tn_zuri", ORDER, "ZURIBEANS-ZA", 4, "erp_commerceorder", status, "pending", "pending",
                                self.revision, datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc))

    def open_order(self, **kw):
        self.calls.append(("open", kw["commerce_order_id"], kw["order_version"], kw["erp_order_id"]))
        return self._record()

    def link_document(self, *, tenant_id, document_type, document_id, commerce_order_id):
        self.docs[(document_type, document_id)] = commerce_order_id
        self.calls.append(("link", document_type))
        return True

    def order_of_document(self, tenant_id, document_type, document_id):
        return self.docs.get((document_type, document_id))

    def record_fact(self, *, tenant_id, commerce_order_id, fact, now, invoice_id=None):
        self.calls.append(("fact", fact, invoice_id))
        changed = fact not in self.facts
        self.facts.add(fact)
        if changed:
            self.revision += 1
        return SimpleNamespace(record=self._record("processing"), changed=changed)


class FakeMappings(FakeMappingStore):
    def erp_resource_id(self, tenant_id, canonical_type, canonical_id):
        return f"erp_{canonical_type.lower()}"


class ServiceHookTests(unittest.TestCase):
    def setUp(self):
        self.idempiere, self.mappings, self.outbox = FakeIdempiereClient(), FakeMappings(), FakeOutboxStore()
        self.consequences = RecordingConsequences()

    def create(self, **kw):
        return service.create_sales_order(
            scope=SCOPE, commerce_order_canonical_id=ORDER, business_partner_native_id=1, document_currency="ZAR",
            lines=(OrderLine("p", "1", "1.00"),), idempiere=self.idempiere, mappings=self.mappings,
            consequences=self.consequences, outbox=self.outbox, **kw)

    def test_no_order_version_means_no_record_and_never_a_guessed_version(self):
        self.create()
        self.assertEqual(self.consequences.calls, [])

    def test_the_full_sequence_records_each_fact_against_the_right_order(self):
        self.create(order_version=4)
        service.complete_sales_order(scope=SCOPE, commerce_order_canonical_id=ORDER, correlation_id="c",
                                     process_ids=PROCESS_IDS, idempiere=self.idempiere, mappings=self.mappings,
                                     outbox=self.outbox, consequences=self.consequences)
        service.create_shipment(scope=SCOPE, shipment_canonical_id="22222222-2222-4222-8222-222222222222",
                                commerce_order_canonical_id=ORDER, idempiere=self.idempiere, mappings=self.mappings,
                                consequences=self.consequences)
        service.complete_shipment(scope=SCOPE, shipment_canonical_id="22222222-2222-4222-8222-222222222222",
                                  correlation_id="c", process_ids=PROCESS_IDS, idempiere=self.idempiere,
                                  mappings=self.mappings, outbox=self.outbox, consequences=self.consequences)
        invoice = service.create_customer_invoice(scope=SCOPE, commerce_order_canonical_id=ORDER,
                                                  idempiere=self.idempiere, mappings=self.mappings,
                                                  consequences=self.consequences)
        service.post_customer_invoice(scope=SCOPE, invoice_canonical_id=invoice.canonical_id, correlation_id="c",
                                      process_ids=PROCESS_IDS, idempiere=self.idempiere, mappings=self.mappings,
                                      outbox=self.outbox, consequences=self.consequences)
        facts = [c for c in self.consequences.calls if c[0] == "fact"]
        self.assertEqual([f[1] for f in facts], [Fact.ORDER_COMPLETED, Fact.SHIPMENT_COMPLETED, Fact.INVOICE_POSTED])
        self.assertEqual(facts[2][2], "erp_customerinvoice", "the public erp_ id, never the native id")
        self.assertEqual(self.consequences.calls[0], ("open", ORDER, 4, "erp_commerceorder"))

    def test_a_change_announces_the_registered_event_once_and_a_repeat_announces_nothing(self):
        self.create(order_version=4, correlation_id="not-a-uuid")
        for _ in range(2):
            service.complete_sales_order(scope=SCOPE, commerce_order_canonical_id=ORDER, correlation_id="not-a-uuid",
                                         process_ids=PROCESS_IDS, idempiere=self.idempiere, mappings=self.mappings,
                                         outbox=self.outbox, consequences=self.consequences)
        events = self.outbox.events
        self.assertEqual([e.type for e in events], ["com.baobab-platform.erp.order.consequence-changed.v1"] * 2)
        self.assertEqual([e.data["revision"] for e in events], [1, 2])
        self.assertEqual(len({e.id for e in events}), 2)
        self.assertEqual(len({e.correlationid for e in events}), 1, "one stable correlation for the order")

    def test_an_order_without_a_record_announces_nothing(self):
        self.create()
        self.assertFalse(getattr(self.outbox, "events", []))

    def test_a_document_of_an_order_without_a_record_changes_nothing(self):
        self.create()  # no version -> nothing opened
        self.consequences.docs.clear()
        service.complete_sales_order(scope=SCOPE, commerce_order_canonical_id=ORDER, correlation_id="c",
                                     process_ids=PROCESS_IDS, idempiere=self.idempiere, mappings=self.mappings,
                                     outbox=self.outbox, consequences=None)
        self.assertEqual(self.consequences.calls, [])


if __name__ == "__main__":
    unittest.main()


class ConsequenceEventTests(unittest.TestCase):
    RECORD = OrderConsequence("tn_zuri", ORDER, "ZURIBEANS-ZA", 2, "erp_abc12345", "posted", "posted", "fulfilled", 4,
                              datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), invoice_id="erp_inv12345")

    def test_the_event_is_the_registered_type_carrying_exactly_the_read_models_document(self):
        from order_to_cash.consequence_events import EVENT_TYPE, consequence_changed_event
        event = consequence_changed_event(self.RECORD, None)
        self.assertEqual((event.type, event.subject, event.tenantid, event.baobabscope),
                         (EVENT_TYPE, f"order:{ORDER}", "tn_zuri", "tenant"))
        self.assertEqual(event.data, self.RECORD.to_contract())
        self.assertEqual(event.time, self.RECORD.updated_at)
        self.assertEqual(event.idempotencykey, f"erp-order-consequence-{ORDER}-r4")

    def test_the_id_is_stable_per_revision_and_differs_between_revisions(self):
        from dataclasses import replace
        from order_to_cash.consequence_events import consequence_changed_event
        first = consequence_changed_event(self.RECORD, None)
        self.assertEqual(first.id, consequence_changed_event(self.RECORD, None).id)
        self.assertNotEqual(first.id, consequence_changed_event(replace(self.RECORD, revision=5), None).id)
        self.assertNotEqual(first.id, consequence_changed_event(replace(self.RECORD, commerce_order_id="x" * 8), None).id)

    def test_a_uuid_correlation_is_kept_and_anything_else_is_derived_stably(self):
        from order_to_cash.consequence_events import consequence_changed_event, correlation_uuid
        supplied = "0b1f3a52-6a4b-4f4e-9d52-1a2b3c4d5e6f"
        self.assertEqual(consequence_changed_event(self.RECORD, supplied).correlationid, supplied)
        derived = correlation_uuid("tn_zuri", ORDER, "corr-9")
        self.assertEqual(derived, correlation_uuid("tn_zuri", ORDER, ""))
        self.assertNotEqual(derived, correlation_uuid("tn_other", ORDER, "corr-9"))
