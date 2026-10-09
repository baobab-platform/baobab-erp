"""LA-05D3 real ERP invoice-post boundary only calls iDempiere when governed."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from order_to_cash.governed_service import post_customer_invoice_governed
from order_to_cash.legal_actor_gate import LegalActorNotAuthorised, LegalActorOperation
from order_to_cash.model import TenantScope
from order_to_cash.service import ProcessIds

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
SCOPE = TenantScope("tn-operating", "LE-SYNTHETIC-ISSUER", 12, 0)
OPERATION = LegalActorOperation(
    context_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
    tenant_id=SCOPE.tenant_id,
    operating_organisation_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
    expected_legal_entity_id=SCOPE.legal_entity_id,
    role="INVOICE_ISSUER",
    activity="B2B_INVOICE", market="ZA",
    capability="accounting.customer-invoice.post",
    operation_reference="invoice-synthetic-123",
)

def decision(outcome="AUTHORIZED"):
    return {
        "context_id": OPERATION.context_id,
        "operation_reference": OPERATION.operation_reference,
        "provider_permissions_granted": False,
        "legal_actor_resolution": {
            "outcome": outcome, "policy_reference": "ADR-BCP-027",
            "mandate_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d",
            "responsible_legal_entity_id": SCOPE.legal_entity_id,
            "evidence_references": ["synthetic/official-registry"],
            "evaluated_at": NOW.isoformat(),
            "valid_until": (NOW+timedelta(seconds=15)).isoformat(),
        },
    }


class Assessor:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def assess(self, operation):
        self.calls += 1
        return self.result


class Provider:
    def __init__(self, ready=True):
        self.ready, self.calls = ready, 0

    def ensure_legal_actor_usable(self, operation, mandate):
        self.calls += 1
        if not self.ready:
            raise LegalActorNotAuthorised("native finance role not ready")


def invoke(*, operation=OPERATION, assessor=None, provider=None):
    return post_customer_invoice_governed(
        operation=operation, assessor=assessor or Assessor(decision()),
        provider=provider or Provider(), scope=SCOPE,
        invoice_canonical_id=OPERATION.operation_reference,
        correlation_id="synthetic-correlation-id",
        process_ids=ProcessIds(1,2,3,4,5),
        idempiere=None, mappings=None, outbox=None, now=lambda: NOW,
    )


class TestGovernedInvoicePosting(unittest.TestCase):
    def test_exact_issuer_and_finance_readiness_before_native_process_each_time(self):
        assessor, provider = Assessor(decision()), Provider()
        with patch("order_to_cash.governed_service.post_customer_invoice") as native:
            invoke(assessor=assessor, provider=provider)
            invoke(assessor=assessor, provider=provider)
            self.assertEqual(native.call_count, 2)
            self.assertEqual((assessor.calls, provider.calls), (2,2))

    def test_mismatched_tenant_role_actor_capability_or_reference_blocks_native(self):
        cases = [
            replace(OPERATION, tenant_id="tn-foreign"),
            replace(OPERATION, role="ACCOUNTING_ENTITY"),
            replace(OPERATION, expected_legal_entity_id="LE-FOREIGN"),
            replace(OPERATION, operation_reference="invoice-other"),
            replace(OPERATION, capability="inventory.write"),
        ]
        for operation in cases:
            with self.subTest(operation=operation):
                with patch("order_to_cash.governed_service.post_customer_invoice") as native:
                    with self.assertRaises(LegalActorNotAuthorised):
                        invoke(operation=operation)
                    native.assert_not_called()

    def test_revoked_or_unavailable_cp_denies_before_invoice_post(self):
        with patch("order_to_cash.governed_service.post_customer_invoice") as native:
            with self.assertRaises(LegalActorNotAuthorised):
                invoke(assessor=Assessor(decision("REVOKED_OR_EXPIRED")))
            native.assert_not_called()

    def test_provider_not_approved_blocks_even_with_cp_authorization(self):
        with patch("order_to_cash.governed_service.post_customer_invoice") as native:
            with self.assertRaises(LegalActorNotAuthorised):
                invoke(provider=Provider(False))
            native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
