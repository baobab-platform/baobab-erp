"""LA-05 ERP native REST egress regression and negative security tests.

All fixtures are synthetic. Private execution markers model the *outcome* of
the governed CP/documentary/provider path, not actual external acceptance.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from integration.idempiere_client import (
    IdempiereCredentials, RestIdempiereClient,
)
from integration.native_finance_guard import (
    NativeFinancialMutationDenied, require_native_financial_authority,
)
from order_to_cash.model import TenantScope
from order_to_cash.service import _authorised_invoice_post, _authorised_native_action


_SCOPE = TenantScope("tenant-test-only", "entity-test-only", 11, 7)
_PROCESS_IDS = {
    "IDEMPIERE_PROCESS_COMPLETE_SALES_ORDER": "3001",
    "IDEMPIERE_PROCESS_COMPLETE_SHIPMENT": "3002",
    "IDEMPIERE_PROCESS_POST_CUSTOMER_INVOICE": "3003",
    "IDEMPIERE_PROCESS_COMPLETE_PAYMENT": "3004",
    "IDEMPIERE_PROCESS_ALLOCATE_PAYMENT": "3005",
}
_ENV = {
    "BAOBAB_DEPLOYMENT_ENV": "staging",
    "BAOBAB_REQUIRE_LEGAL_ACTOR_GATE": "true",
    **_PROCESS_IDS,
}
_CREDS = IdempiereCredentials(
    base_url="https://invalid.example",
    username="synthetic", password="synthetic",
    client_id=11, role_id=3, organization_id=7,
)


class NativeRestFinanceGuardTest(unittest.TestCase):
    def check(self, method, path, data=None, creds=_CREDS):
        return require_native_financial_authority(method, path, data, creds)

    def test_unapproved_native_creates_and_processes_fail_before_transport(self):
        with patch.dict(os.environ, _ENV):
            for table in ("C_Order", "C_Invoice", "M_InOut", "C_Payment",
                          "Fact_Acct", "GL_Journal", "C_Tax", "C_InvoiceLine"):
                with self.subTest(table=table), self.assertRaises(NativeFinancialMutationDenied):
                    self.check("POST", f"/models/{table}", {"AD_Client_ID": 11})
            for process_id, params in (
                ("3001", {"C_Order_ID": 12, "DocAction": "CO"}),
                ("3003", {"C_Invoice_ID": 5, "DocAction": "CO"}),
                ("3004", {"C_Payment_ID": 30, "DocAction": "CO"}),
                ("7777", {"record-id": 3}),
            ):
                with self.subTest(process_id=process_id), self.assertRaises(NativeFinancialMutationDenied):
                    self.check("POST", f"/processes/{process_id}", params)
            client = RestIdempiereClient(_CREDS)
            with patch.object(client, "_ensure_token") as authenticate:
                with self.assertRaises(NativeFinancialMutationDenied):
                    client.create_record("C_Invoice", {"PayAmt": "10"})
                authenticate.assert_not_called()

    def test_finance_edits_delete_and_undocumented_records_always_denied(self):
        with patch.dict(os.environ, _ENV), _authorised_invoice_post(_SCOPE, "invoice-test-only"):
            for method, path, payload in (
                ("PUT", "/models/C_Invoice/1", {"DocStatus": "CO"}),
                ("DELETE", "/models/C_Invoice/1", {}),
                ("POST", "/models/C_InvoiceLine", {"QtyInvoiced": 9}),
                ("POST", "/models/Fact_Acct", {"AmtAcctDr": 100}),
                ("POST", "/models/C_Tax", {"Rate": "0"}),
            ):
                with self.subTest(method=method, path=path), self.assertRaises(NativeFinancialMutationDenied):
                    self.check(method, path, payload)

    def test_native_created_document_requires_exact_action_and_company(self):
        with patch.dict(os.environ, _ENV), _authorised_native_action(_SCOPE, "create_sales_order", "order-test-only"):
            self.check("POST", "/models/C_Order", {"POReference": "order-test-only"})
            self.check("POST", "/models/C_Order", {"AD_Client_ID": 11, "AD_Org_ID": 7})
            for path, payload in (
                ("/models/C_Invoice", {}),
                ("/models/M_InOut", {}),
                ("/models/C_Order", {"AD_Client_ID": 99}),
                ("/models/C_Order", {"AD_Org_ID": 999}),
                ("/models/C_Order?expand=1", {}),
            ):
                with self.subTest(path=path, payload=payload), self.assertRaises(NativeFinancialMutationDenied):
                    self.check("POST", path, payload)
            wrong_org = IdempiereCredentials(**{
                **_CREDS.__dict__, "organization_id": 10,
            })
            with self.assertRaises(NativeFinancialMutationDenied):
                self.check("POST", "/models/C_Order", {}, wrong_org)

    def test_governed_document_processing_is_action_and_process_id_specific(self):
        samples = (
            ("complete_sales_order", "3001", {"C_Order_ID": 5, "DocAction": "CO"}),
            ("complete_shipment", "3002", {"M_InOut_ID": 5, "DocAction": "CO"}),
            ("complete_payment", "3004", {"C_Payment_ID": 5, "DocAction": "CO"}),
            ("allocate_payment", "3005", {"C_Payment_ID": 5, "C_Invoice_ID": 6, "Amount": "8.00"}),
        )
        with patch.dict(os.environ, _ENV):
            for action, process_id, params in samples:
                with self.subTest(action=action), _authorised_native_action(_SCOPE, action, "operation-test-only"):
                    self.check("POST", "/processes/" + process_id, params)
                    with self.assertRaises(NativeFinancialMutationDenied):
                        self.check("POST", "/processes/9999", params)
                    with self.assertRaises(NativeFinancialMutationDenied):
                        self.check("POST", "/processes/3003", {"C_Invoice_ID": 5, "DocAction": "CO"})
            with _authorised_invoice_post(_SCOPE, "invoice-test-only"):
                self.check("POST", "/processes/3003", {"C_Invoice_ID": 5, "DocAction": "CO"})
                with self.assertRaises(NativeFinancialMutationDenied):
                    self.check("POST", "/processes/3004", {"C_Payment_ID": 5, "DocAction": "CO"})
            # Process IDs are deployment-controlled and must not be inferred.
            with patch.dict(os.environ, {"IDEMPIERE_PROCESS_POST_CUSTOMER_INVOICE": ""}):
                with _authorised_invoice_post(_SCOPE, "invoice-test-only"):
                    with self.assertRaises(NativeFinancialMutationDenied):
                        self.check("POST", "/processes/3003", {"C_Invoice_ID": 5, "DocAction": "CO"})

    def test_error_closes_on_malformed_payload_and_context_is_revoked(self):
        with patch.dict(os.environ, _ENV):
            with _authorised_native_action(_SCOPE, "complete_payment", "payment-test-only"):
                for params in (
                    {"C_Payment_ID": True, "DocAction": "CO"},
                    {"C_Payment_ID": 0, "DocAction": "CO"},
                    {"C_Payment_ID": 42, "DocAction": "VO"},
                    {"C_Payment_ID": 42, "DocAction": "CO", "C_Invoice_ID": 45},
                ):
                    with self.subTest(params=params), self.assertRaises(NativeFinancialMutationDenied):
                        self.check("POST", "/processes/3004", params)
            with self.assertRaises(NativeFinancialMutationDenied):
                self.check("POST", "/processes/3004", {"C_Payment_ID": 42, "DocAction": "CO"})

    def test_development_bypass_is_only_explicit_local_mode(self):
        with patch.dict(os.environ, {"BAOBAB_DEPLOYMENT_ENV": "development",
                                    "BAOBAB_REQUIRE_LEGAL_ACTOR_GATE": "false"}):
            self.check("POST", "/models/C_Invoice", {})
        with patch.dict(os.environ, {"BAOBAB_DEPLOYMENT_ENV": "unknown",
                                    "BAOBAB_REQUIRE_LEGAL_ACTOR_GATE": "false"}):
            with self.assertRaises(NativeFinancialMutationDenied):
                self.check("POST", "/models/C_Invoice", {})


if __name__ == "__main__":
    unittest.main()
