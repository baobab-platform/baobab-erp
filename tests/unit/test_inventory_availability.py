import unittest
from decimal import Decimal

from integration.idempiere_client import Eq, IdempiereClientError
from inventory.availability import IdempiereStockReader, StockFacts, StockReadError, decimal_string

PRODUCT, WAREHOUSE = 1000012, 1000003


class FakeEngine:
    """Answers the five reads the stock reader makes, in the REST plugin's shapes."""

    def __init__(self):
        self.records = {("M_Product", PRODUCT): {"id": PRODUCT, "C_UOM_ID": {"id": 100, "identifier": "Each"}},
                        ("C_UOM", 100): {"id": 100, "X12DE355": "EA"}}
        self.lists = {
            "M_Locator": [{"M_Locator_ID": 11}, {"M_Locator_ID": 12}],
            "M_StorageOnHand": [
                {"M_Locator_ID": {"id": 11}, "QtyOnHand": 30, "Updated": "2026-10-01T08:00:00Z"},
                {"M_Locator_ID": 12, "QtyOnHand": "12.5", "Updated": "2026-10-02T09:00:00Z"},
                {"M_Locator_ID": 99, "QtyOnHand": 1000, "Updated": "2026-12-31T00:00:00Z"},  # another warehouse
            ],
            "M_StorageReservation": [{"Qty": 8, "Updated": "2026-10-02T10:00:00Z"}],
        }
        self.queries = []

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def query(self, table, conditions, select):
        self.queries.append((table, list(conditions)))
        return self.lists[table]


def read(engine):
    return IdempiereStockReader(engine).read(product_native_id=PRODUCT, warehouse_native_id=WAREHOUSE)


class StockReaderTests(unittest.TestCase):
    def test_on_hand_sums_only_the_warehouse_locators_and_available_is_the_difference(self):
        facts = read(FakeEngine())
        self.assertEqual((facts.on_hand, facts.allocated, facts.available, facts.unit),
                         (Decimal("42.5"), Decimal(8), Decimal("34.5"), "EA"))

    def test_revision_is_the_latest_updated_instant_of_the_rows_read_only(self):
        facts = read(FakeEngine())
        self.assertEqual(facts.revision, 1790935200)  # 2026-10-02T10:00:00Z; the other warehouse's row is ignored

    def test_the_queries_are_scoped_to_the_product_warehouse_and_sales_reservations(self):
        engine = FakeEngine()
        read(engine)
        queries = dict(engine.queries)
        self.assertEqual(queries["M_Locator"], [Eq("M_Warehouse_ID", WAREHOUSE)])
        self.assertEqual(queries["M_StorageOnHand"], [Eq("M_Product_ID", PRODUCT)])
        self.assertEqual(queries["M_StorageReservation"],
                         [Eq("M_Product_ID", PRODUCT), Eq("M_Warehouse_ID", WAREHOUSE), Eq("IsSOTrx", True)])

    def test_over_allocation_never_reports_negative_availability(self):
        engine = FakeEngine()
        engine.lists["M_StorageReservation"] = [{"Qty": 100, "Updated": "2026-10-02T10:00:00Z"}]
        facts = read(engine)
        self.assertEqual((facts.available, facts.allocated > facts.on_hand), (Decimal(0), True))

    def test_no_stock_rows_is_zero_with_revision_one(self):
        engine = FakeEngine()
        engine.lists["M_StorageOnHand"], engine.lists["M_StorageReservation"] = [], []
        facts = read(engine)
        self.assertEqual((facts.on_hand, facts.allocated, facts.available, facts.revision), (0, 0, 0, 1))

    def test_a_response_that_is_not_stock_is_a_read_error_not_a_guess(self):
        def broken(mutate):
            engine = FakeEngine()
            mutate(engine)
            with self.assertRaises(StockReadError):
                read(engine)
        broken(lambda e: e.records.update({("M_Product", PRODUCT): {"id": PRODUCT}}))
        broken(lambda e: e.records.update({("C_UOM", 100): {"id": 100, "X12DE355": "bad unit"}}))
        broken(lambda e: e.records.update({("C_UOM", 100): {"id": 100}}))
        broken(lambda e: e.lists["M_StorageOnHand"].append({"M_Locator_ID": 11, "QtyOnHand": "n/a", "Updated": "2026-10-02T09:00:00Z"}))
        broken(lambda e: e.lists["M_StorageOnHand"].append({"M_Locator_ID": 11, "QtyOnHand": 1}))
        broken(lambda e: e.lists["M_StorageOnHand"].append({"M_Locator_ID": 11, "QtyOnHand": 1, "Updated": "yesterday"}))
        broken(lambda e: e.lists["M_StorageOnHand"].append({"QtyOnHand": 1, "Updated": "2026-10-02T09:00:00Z"}))
        broken(lambda e: e.lists["M_StorageReservation"].append({"Qty": True, "Updated": "2026-10-02T09:00:00Z"}))

    def test_an_engine_failure_propagates_for_the_caller_to_answer_503(self):
        engine = FakeEngine()
        engine.query = lambda *a, **k: (_ for _ in ()).throw(IdempiereClientError("down"))
        with self.assertRaises(IdempiereClientError):
            read(engine)


class DecimalStringTests(unittest.TestCase):
    def test_the_contract_decimal_has_no_exponent_or_float_noise(self):
        for value, text in ((Decimal("42.50"), "42.5"), (Decimal("1E+2"), "100"), (Decimal(0), "0"), (Decimal("-0"), "0"),
                            (Decimal("0.000001"), "0.000001"), (Decimal("12345678901234567890.5"), "12345678901234567890.5")):
            with self.subTest(text):
                self.assertEqual(decimal_string(value), text)

    def test_facts_available_is_floored_at_zero(self):
        self.assertEqual(StockFacts(Decimal(1), Decimal(5), "EA", 1).available, Decimal(0))


if __name__ == "__main__":
    unittest.main()
