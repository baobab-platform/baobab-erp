import unittest

from mapping.model import MappingNotFoundError, NativeRecordRef
from order_to_cash import service
from order_to_cash.model import OrderLine, OrderToCashError, TenantScope

SCOPE = TenantScope(tenant_id="zuribeans-ug", legal_entity_id="zuribeans-ug-legal", ad_client_id=1001, ad_org_id=1)

PROCESS_IDS = service.ProcessIds(
    complete_sales_order=1001,
    complete_shipment=1002,
    post_customer_invoice=1003,
    complete_payment=1004,
    allocate_payment=1005,
)


class FakeIdempiereClient:
    def __init__(self):
        self.next_id = 100
        self.created: list[tuple[str, dict]] = []
        self.processes_executed: list[tuple[int, dict]] = []

    def create_record(self, table, fields):
        self.created.append((table, fields))
        self.next_id += 1
        return self.next_id

    def execute_process(self, process_id, parameters):
        self.processes_executed.append((process_id, parameters))
        return {"ok": True}


class FakeMappingStore:
    def __init__(self):
        self._by_canonical: dict[tuple[str, str, str], NativeRecordRef] = {}

    def create_mapping(self, tenant_id, legal_entity_id, canonical_type, canonical_id, native_table, native_id):
        key = (tenant_id, canonical_type, canonical_id)
        if key in self._by_canonical:
            raise ValueError(f"mapping already exists for {key}")
        self._by_canonical[key] = NativeRecordRef(table=native_table, record_id=native_id)

    def find_native(self, tenant_id, canonical_type, canonical_id):
        return self._by_canonical.get((tenant_id, canonical_type, canonical_id))


class FakeOutboxStore:
    def __init__(self):
        self.recorded = []

    def record(self, envelope):
        self.recorded.append(envelope)


class SalesOrderTests(unittest.TestCase):
    def setUp(self):
        self.idempiere = FakeIdempiereClient()
        self.mappings = FakeMappingStore()
        self.outbox = FakeOutboxStore()

    def test_create_then_complete_emits_exactly_one_accepted_event(self):
        lines = (OrderLine(product_canonical_id="prod-1", quantity="10", unit_price="4.50"),)
        ref = service.create_sales_order(
            scope=SCOPE,
            commerce_order_canonical_id="commerce-order-1",
            business_partner_native_id=42,
            document_currency="UGX",
            lines=lines,
            idempiere=self.idempiere,
            mappings=self.mappings,
        )
        self.assertEqual(ref.table, "C_Order")
        self.assertEqual(self.outbox.recorded, [])  # creation alone is not yet a canonical fact

        service.complete_sales_order(
            scope=SCOPE,
            commerce_order_canonical_id="commerce-order-1",
            correlation_id="corr-1",
            process_ids=PROCESS_IDS,
            idempiere=self.idempiere,
            mappings=self.mappings,
            outbox=self.outbox,
        )
        self.assertEqual(len(self.outbox.recorded), 1)
        envelope = self.outbox.recorded[0]
        self.assertEqual(envelope.event_type, "erp.sales-order.accepted.v1")
        self.assertEqual(envelope.tenant_id, SCOPE.tenant_id)
        # native process invoked, never a direct DocStatus field patch
        self.assertEqual(self.idempiere.processes_executed[0][0], PROCESS_IDS.complete_sales_order)

    def test_create_sales_order_requires_at_least_one_line(self):
        with self.assertRaises(OrderToCashError):
            service.create_sales_order(
                scope=SCOPE,
                commerce_order_canonical_id="commerce-order-empty",
                business_partner_native_id=42,
                document_currency="UGX",
                lines=(),
                idempiere=self.idempiere,
                mappings=self.mappings,
            )

    def test_complete_without_create_fails_closed(self):
        with self.assertRaises(MappingNotFoundError):
            service.complete_sales_order(
                scope=SCOPE,
                commerce_order_canonical_id="never-created",
                correlation_id="corr-2",
                process_ids=PROCESS_IDS,
                idempiere=self.idempiere,
                mappings=self.mappings,
                outbox=self.outbox,
            )


class ShipmentInvoicePaymentFlowTests(unittest.TestCase):
    def setUp(self):
        self.idempiere = FakeIdempiereClient()
        self.mappings = FakeMappingStore()
        self.outbox = FakeOutboxStore()
        service.create_sales_order(
            scope=SCOPE,
            commerce_order_canonical_id="commerce-order-9",
            business_partner_native_id=7,
            document_currency="UGX",
            lines=(OrderLine("prod-9", "1", "100.00"),),
            idempiere=self.idempiere,
            mappings=self.mappings,
        )
        service.complete_sales_order(
            scope=SCOPE,
            commerce_order_canonical_id="commerce-order-9",
            correlation_id="corr-9",
            process_ids=PROCESS_IDS,
            idempiere=self.idempiere,
            mappings=self.mappings,
            outbox=self.outbox,
        )

    def test_full_sell_side_sequence_emits_five_distinct_facts_in_order(self):
        service.create_shipment(
            scope=SCOPE, shipment_canonical_id="ship-9", commerce_order_canonical_id="commerce-order-9",
            idempiere=self.idempiere, mappings=self.mappings,
        )
        service.complete_shipment(
            scope=SCOPE, shipment_canonical_id="ship-9", correlation_id="corr-9", process_ids=PROCESS_IDS,
            idempiere=self.idempiere, mappings=self.mappings, outbox=self.outbox,
        )
        invoice_ref = service.create_customer_invoice(
            scope=SCOPE, commerce_order_canonical_id="commerce-order-9",
            idempiere=self.idempiere, mappings=self.mappings,
        )
        service.post_customer_invoice(
            scope=SCOPE, invoice_canonical_id=invoice_ref.canonical_id, correlation_id="corr-9",
            process_ids=PROCESS_IDS, idempiere=self.idempiere, mappings=self.mappings, outbox=self.outbox,
        )
        service.create_payment(
            scope=SCOPE, payment_canonical_id="pay-9", business_partner_native_id=7,
            amount="100.00", currency="UGX", idempiere=self.idempiere, mappings=self.mappings,
        )
        service.complete_payment(
            scope=SCOPE, payment_canonical_id="pay-9", correlation_id="corr-9", process_ids=PROCESS_IDS,
            idempiere=self.idempiere, mappings=self.mappings, outbox=self.outbox,
        )
        service.allocate_payment(
            scope=SCOPE, payment_canonical_id="pay-9", invoice_canonical_id=invoice_ref.canonical_id,
            amount="100.00", correlation_id="corr-9", process_ids=PROCESS_IDS,
            idempiere=self.idempiere, mappings=self.mappings, outbox=self.outbox,
        )

        event_types = [envelope.event_type for envelope in self.outbox.recorded]
        self.assertEqual(
            event_types,
            [
                "erp.sales-order.accepted.v1",
                "erp.goods-shipment.completed.v1",
                "erp.customer-invoice.posted.v1",
                "erp.payment.completed.v1",
                "erp.payment.allocated.v1",
            ],
        )
        # every event is genuinely distinct -- no step's outcome is silently reused for another
        self.assertEqual(len(set(event_types)), 5)

    def test_shipment_against_unknown_order_fails_closed(self):
        with self.assertRaises(MappingNotFoundError):
            service.create_shipment(
                scope=SCOPE, shipment_canonical_id="ship-x", commerce_order_canonical_id="no-such-order",
                idempiere=self.idempiere, mappings=self.mappings,
            )

    def test_resolving_wrong_document_type_fails_closed(self):
        # commerce-order-9's mapping points at C_Order; asking create_shipment
        # machinery's own resolver to treat it as a GoodsShipment must fail,
        # not silently resolve the wrong table.
        with self.assertRaises(OrderToCashError):
            service._resolve_native(
                scope=SCOPE,
                canonical_type="CommerceOrder",
                canonical_id="commerce-order-9",
                expected_table="M_InOut",
                mappings=self.mappings,
            )


if __name__ == "__main__":
    unittest.main()
