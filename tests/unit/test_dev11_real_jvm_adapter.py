"""DEV-11 disposable real JVM adapter: fail-closed unit tests only.

These tests MOCK *negative* database requests and reject wrong identities.
They DO NOT certify any native iDempiere order or CP decision; those
positive proofs require the independently queried real engine and CP.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.idempiere_client import Eq, IdempiereClientError
from integration.idempiere_gate_d_real import RealJvmGateDOrderAdapter

ENV = {
    "BAOBAB_ENVIRONMENT": "integration",
    "BAOBAB_ERP_INBOX_PROFILE": "dev11-order-placed",
    "BAOBAB_REQUIRE_LEGAL_ACTOR_GATE": "true",
    "BAOBAB_DEV11_REAL_JVM_GATE_ENABLED": "true",
    "BAOBAB_DEPLOYMENT_ENV": "integration",
}


class AdapterUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.driver = Path(self.tmp.name) / "driver"
        self.driver.mkdir()
        (self.driver / "ready").write_text("ready\n")
        (self.driver / "requests").mkdir()
        (self.driver / "results").mkdir()
        self.environ = patch.dict(os.environ, ENV)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def adapter(self, client=11, org=11):
        return RealJvmGateDOrderAdapter(
            client, org, db_url="postgresql://unreachable.invalid:5432/idempiere",
            driver_dir=str(self.driver))

    def test_exact_protected_profile_only(self):
        self.assertEqual(self.adapter().client_id, 11)
        for key, value in (
            ("BAOBAB_ENVIRONMENT", "production"),
            ("BAOBAB_DEPLOYMENT_ENV", "production"),
            ("BAOBAB_REQUIRE_LEGAL_ACTOR_GATE", "false"),
            ("BAOBAB_ERP_INBOX_PROFILE", "normal"),
            ("BAOBAB_DEV11_REAL_JVM_GATE_ENABLED", "false"),
        ):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaisesRegex(
                        IdempiereClientError, "DEV11_NATIVE_JVM_GATE_NOT_AUTHORISED"):
                    self.adapter()

    def test_no_foreign_company_or_org(self):
        for client, org in ((12, 11), (11, 12), (0, 0)):
            with self.subTest(client=client, org=org):
                with self.assertRaises(IdempiereClientError):
                    self.adapter(client, org)

    def test_symlinked_driver_root_denied(self):
        alias = Path(self.tmp.name) / "link"
        alias.symlink_to(self.driver, target_is_directory=True)
        with self.assertRaisesRegex(
                IdempiereClientError, "DEV11_GATE_DRIVER_DIRECTORY_INVALID"):
            RealJvmGateDOrderAdapter(
                11, 11, db_url="postgresql://private.invalid/idempiere",
                driver_dir=str(alias))

    def test_no_generic_table_read_or_native_sql(self):
        adapter = self.adapter()
        with self.assertRaisesRegex(IdempiereClientError, "READ_TABLE_NOT_ALLOWED"):
            adapter.get_record("Fact_Acct", 11)
        with self.assertRaisesRegex(IdempiereClientError, "QUERY_NOT_ALLOWED"):
            adapter.query("C_Invoice", [Eq("Name", "x")], ["id"])
        with self.assertRaisesRegex(IdempiereClientError, "QUERY_NOT_ALLOWED"):
            adapter.query("C_Order", [Eq("AD_Client_ID", 11)], ["C_Order_ID"])

    def test_no_foreign_native_action(self):
        adapter = self.adapter()
        with self.assertRaisesRegex(IdempiereClientError, "CREATE_NOT_ALLOWED"):
            adapter.create_record("C_Payment", {})
        with self.assertRaisesRegex(IdempiereClientError, "SINGLE_LINE_REQUIRED"):
            adapter.create_record("C_Order", {
                "C_BPartner_ID": 11, "CurrencyISO": "USD",
                "POReference": "order_dev11_fixture", "OrderLines": [],
            })

    def test_readback_denies_false_company_even_with_matching_reference(self):
        a = self.adapter()
        def queried(sql, params):
            if "FROM adempiere.c_order o" in sql:
                return [{
                    "c_order_id": 500, "ad_client_id": 12,
                    "ad_org_id": 11, "c_bpartner_id": 17,
                    "poreference": "order_dev11_fixture", "issotrx": "Y",
                    "iso_code": "USD",
                }]
            if "FROM adempiere.c_orderline" in sql:
                return [{"m_product_id": 13, "qtyordered": 2,
                         "priceentered": 10}]
            raise AssertionError("Unexpected SQL")
        with patch.object(a, "_sql", side_effect=queried):
            with self.assertRaisesRegex(IdempiereClientError, "BUSINESS_FACTS_MISMATCH"):
                a._readback(500, {
                    "C_BPartner_ID": 17, "CurrencyISO": "USD",
                    "POReference": "order_dev11_fixture",
                    "OrderLines": [{"M_Product_ID": "13", "QtyOrdered": "2",
                                    "PriceEntered": "10.00"}],
                })


if __name__ == "__main__":
    unittest.main()
