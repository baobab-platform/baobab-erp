"""Relational selector regressions; these do not qualify native ERP effects.

SQLite exercises the ANSI customer/location predicates with actual rows.
PostgreSQL 17, CP and the protected JVM remain mandatory connected gates.
"""
from pathlib import Path
import sqlite3
import sys
import unittest

DRIVER = Path(__file__).resolve().parents[2] / "idempiere/acceptance/erp-a/driver"
sys.path.insert(0, str(DRIVER))
try:
    from dev11_native_connected import native_customer
finally:
    sys.path.remove(str(DRIVER))


class NativeCustomerSelectorTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS adempiere")
        self.db.execute("""CREATE TABLE adempiere.c_bpartner (
            c_bpartner_id INTEGER, ad_client_id INTEGER, ad_org_id INTEGER,
            iscustomer TEXT, isactive TEXT)""")
        self.db.execute("""CREATE TABLE adempiere.c_bpartner_location (
            c_bpartner_id INTEGER, isactive TEXT, isbillto TEXT, isshipto TEXT)""")

    def partner(self, *, client=11, org=11, active="Y", customer="Y"):
        self.db.execute("INSERT INTO adempiere.c_bpartner VALUES (101,?,?,?,?)",
                        (client, org, customer, active))

    def location(self, billing, shipping, active="Y"):
        self.db.execute("INSERT INTO adempiere.c_bpartner_location VALUES (101,?,?,?)",
                        (active, billing, shipping))

    def test_separate_billing_and_shipping_locations_are_usable(self):
        self.partner()
        self.location("Y", "N")
        self.location("N", "Y")
        self.assertEqual(native_customer(self.db), 101)

    def test_shared_billing_and_shipping_location_is_usable(self):
        self.partner(org=0)
        self.location("Y", "Y")
        self.assertEqual(native_customer(self.db), 101)

    def test_customer_and_location_boundaries_remain_closed(self):
        for defect in ("foreign-client", "foreign-org", "inactive-customer",
                       "not-customer", "no-billing", "no-shipping", "inactive-location"):
            with self.subTest(defect=defect):
                self.db.execute("DELETE FROM adempiere.c_bpartner")
                self.db.execute("DELETE FROM adempiere.c_bpartner_location")
                self.partner(client=12 if defect == "foreign-client" else 11,
                             org=12 if defect == "foreign-org" else 11,
                             active="N" if defect == "inactive-customer" else "Y",
                             customer="N" if defect == "not-customer" else "Y")
                self.location("N" if defect == "no-billing" else "Y",
                              "N" if defect == "no-shipping" else "Y",
                              "N" if defect == "inactive-location" else "Y")
                self.assertIsNone(native_customer(self.db))


if __name__ == "__main__":
    unittest.main()
