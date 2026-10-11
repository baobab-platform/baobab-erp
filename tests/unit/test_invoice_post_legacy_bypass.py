"""LA-05D4: legacy invoice posting never bypasses CP in protected runtimes."""
from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from order_to_cash.model import OrderToCashError, TenantScope
from order_to_cash.service import (
    ProcessIds,
    _authorised_invoice_post,
    _deny_legacy_invoice_post,
    post_customer_invoice,
)


SCOPE = TenantScope("tn-synthetic", "LE-SYNTHETIC-ISSUER", 12, 0)


class TestLegacyInvoicePostingIsolation(unittest.TestCase):
    def test_staging_and_production_direct_invoice_post_fail_before_mapping_or_idempiere(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment), patch.dict(
                os.environ, {"BAOBAB_DEPLOYMENT_ENV": environment},
            ):
                native, mappings, outbox = Mock(), Mock(), Mock()
                with self.assertRaises(OrderToCashError):
                    post_customer_invoice(
                        scope=SCOPE, invoice_canonical_id="invoice-synthetic-123",
                        correlation_id="test-correlation", process_ids=ProcessIds(1, 2, 3, 4, 5),
                        idempiere=native, mappings=mappings, outbox=outbox,
                    )
                native.execute_process.assert_not_called()
                mappings.find_native.assert_not_called()
                outbox.record.assert_not_called()

    def test_unconfigured_environment_is_protected_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(OrderToCashError):
                _deny_legacy_invoice_post(SCOPE, "invoice-synthetic-123")

    def test_explicit_legal_actor_requirement_closes_legacy_route_even_in_dev(self):
        with patch.dict(os.environ, {
            "BAOBAB_DEPLOYMENT_ENV": "development",
            "BAOBAB_REQUIRE_LEGAL_ACTOR_GATE": "true",
        }):
            with self.assertRaises(OrderToCashError):
                _deny_legacy_invoice_post(SCOPE, "invoice-synthetic-123")

    def test_guarded_execution_permit_is_exact_and_lifetime_bounded(self):
        with patch.dict(os.environ, {"BAOBAB_DEPLOYMENT_ENV": "staging"}):
            with self.assertRaises(OrderToCashError):
                _deny_legacy_invoice_post(SCOPE, "invoice-synthetic-123")
            with _authorised_invoice_post(SCOPE, "invoice-synthetic-123"):
                _deny_legacy_invoice_post(SCOPE, "invoice-synthetic-123")
                with self.assertRaises(OrderToCashError):
                    _deny_legacy_invoice_post(SCOPE, "invoice-another")
                sibling = TenantScope("tn-sibling", SCOPE.legal_entity_id, 12, 0)
                with self.assertRaises(OrderToCashError):
                    _deny_legacy_invoice_post(sibling, "invoice-synthetic-123")
                new_actor = TenantScope(SCOPE.tenant_id, "LE-OTHER", 12, 0)
                with self.assertRaises(OrderToCashError):
                    _deny_legacy_invoice_post(new_actor, "invoice-synthetic-123")
            with self.assertRaises(OrderToCashError):
                _deny_legacy_invoice_post(SCOPE, "invoice-synthetic-123")

    def test_guarded_path_reuses_final_checked_permission_not_request_boolean(self):
        # No request-supplied "governed" flag is accepted by the native API.
        import inspect
        self.assertNotIn("governed", inspect.signature(post_customer_invoice).parameters)
        self.assertNotIn("allowed", inspect.signature(post_customer_invoice).parameters)


if __name__ == "__main__":
    unittest.main()
