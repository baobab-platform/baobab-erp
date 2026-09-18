import unittest
from decimal import Decimal

from integration.trade_projection import Line, ProjectionError, TradeProjection, TransactionKind
from integration.trade_projection_adapter import IdempiereTradeProjectionAdapter


def sales_order(**overrides) -> TradeProjection:
    defaults = dict(
        event_id="e", correlation_id="c", tenant_id="t", legal_entity_id="le-za",
        market_id="za", engine_instance_id="erp", kind=TransactionKind.SALES_ORDER,
        canonical_transaction_id="o1", counterparty_id="bp-1", currency="ZAR",
        lines=(Line("p", Decimal("1"), Decimal("2"), "u"),), contract_version="v1", payload={},
    )
    defaults.update(overrides)
    return TradeProjection(**defaults)


class TradeProjectionTests(unittest.TestCase):
    def test_cross_boundary_identity_is_part_of_digest(self):
        a = sales_order()
        b = sales_order(legal_entity_id="le-ug", market_id="ug", currency="UGX")
        self.assertNotEqual(a.digest(), b.digest())

    def test_counterparty_change_is_part_of_digest(self):
        a = sales_order()
        b = sales_order(counterparty_id="bp-2")
        self.assertNotEqual(a.digest(), b.digest())

    def test_negative_quantity_rejected(self):
        p = sales_order(lines=(Line("p", Decimal("-1"), Decimal("2"), "u"),))
        with self.assertRaises(ProjectionError):
            p.validate()

    def test_payment_kinds_require_no_lines(self):
        p = sales_order(kind=TransactionKind.AR_PAYMENT, lines=())
        p.validate()


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 100

    def create_record(self, table, fields):
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]


class FakeMappings:
    def __init__(self):
        self.values = {}

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        return self.values.get((engine_instance_id, legal_entity_id, kind, canonical_id))

    def put(self, *, engine_instance_id, legal_entity_id, kind, canonical_id, native_id, digest):
        self.values[(engine_instance_id, legal_entity_id, kind, canonical_id)] = (native_id, digest)


class FakeMasterMappings:
    def __init__(self, business_partners=None):
        self.business_partners = {} if business_partners is None else business_partners

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        if kind != "business_partner":
            return None
        native_id = self.business_partners.get(canonical_id)
        return (native_id, "digest", "1") if native_id is not None else None

    def put(self, **kwargs):
        raise AssertionError("adapter never writes master-data mappings")


class IdempiereTradeProjectionAdapterTests(unittest.TestCase):
    def _adapter(self, business_partners=None):
        client = FakeClient()
        mappings = FakeMappings()
        if business_partners is None:
            business_partners = {"bp-1": 900}
        master_mappings = FakeMasterMappings(business_partners)
        return IdempiereTradeProjectionAdapter(client=client, mappings=mappings, master_mappings=master_mappings), client

    def test_project_creates_and_reuses_idempotently(self):
        adapter, client = self._adapter()
        projection = sales_order()

        first = adapter.project(projection)
        second = adapter.project(projection)

        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["native_id"], second["native_id"])
        self.assertEqual(len(client.records), 1)

    def test_changed_projection_after_creation_fails_closed(self):
        adapter, _ = self._adapter()
        projection = sales_order()
        adapter.project(projection)

        changed = sales_order(payload={"Note": "amended"})
        with self.assertRaises(ValueError):
            adapter.project(changed)

    def test_counterparty_without_erp_mapping_fails_closed(self):
        adapter, _ = self._adapter(business_partners={})
        with self.assertRaises(ValueError):
            adapter.project(sales_order())

    def test_sales_order_is_marked_as_sales_side(self):
        adapter, client = self._adapter()
        result = adapter.project(sales_order())
        record = client.records[("C_Order", result["native_id"])]
        self.assertIs(record["IsSOTrx"], True)

    def test_procurement_order_is_marked_as_purchase_side(self):
        adapter, client = self._adapter()
        projection = sales_order(kind=TransactionKind.PROCUREMENT_ORDER, canonical_transaction_id="po1")
        result = adapter.project(projection)
        record = client.records[("C_Order", result["native_id"])]
        self.assertIs(record["IsSOTrx"], False)

    def test_ar_payment_is_marked_as_a_receipt(self):
        adapter, client = self._adapter()
        projection = sales_order(kind=TransactionKind.AR_PAYMENT, canonical_transaction_id="pay1", lines=())
        result = adapter.project(projection)
        record = client.records[("C_Payment", result["native_id"])]
        self.assertIs(record["IsReceipt"], True)

    def test_ap_payment_is_marked_as_a_disbursement(self):
        adapter, client = self._adapter()
        projection = sales_order(kind=TransactionKind.AP_PAYMENT, canonical_transaction_id="pay2", lines=())
        result = adapter.project(projection)
        record = client.records[("C_Payment", result["native_id"])]
        self.assertIs(record["IsReceipt"], False)


if __name__ == "__main__":
    unittest.main()
