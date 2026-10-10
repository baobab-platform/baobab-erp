"""LA-05D: no native ERP financial mutation without current CP and provider proof."""
from datetime import datetime, timedelta, timezone
import unittest
from dataclasses import replace

from order_to_cash.legal_actor_gate import (
    LegalActorNotAuthorised, LegalActorOperation,
    assert_current_decision, perform_governed_financial_action,
)

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
OP = LegalActorOperation(
    context_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
    tenant_id="tn_testoperating",
    operating_organisation_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
    expected_legal_entity_id="LE-TEST-ISSUER",
    role="INVOICE_ISSUER", activity="B2B_COFFEE_INVOICE",
    market="ZA", capability="accounting.customer-invoice.post",
    operation_reference="invoice-123",
)


def decision(*, outcome="AUTHORIZED"):
    return {
        "context_id": OP.context_id, "operation_reference": OP.operation_reference,
        "provider_permissions_granted": False,
        "legal_actor_resolution": {
            "outcome": outcome, "policy_reference": "ADR-BCP-027/LA-04B",
            "evaluated_at": NOW.isoformat(),
            "valid_until": (NOW + timedelta(seconds=20)).isoformat(),
            "mandate_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d",
            "responsible_legal_entity_id": "LE-TEST-ISSUER",
            "evidence_references": ["synthetic/official-reference"],
        },
    }


class Assessor:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def assess(self, request):
        self.calls += 1
        assert request == {
            "context_id": OP.context_id, "role": OP.role,
            "activity": OP.activity, "market": OP.market,
            "capability": OP.capability, "operation_reference": OP.operation_reference,
        }
        return self.result


class NativeReadiness:
    def __init__(self, allowed=True):
        self.allowed, self.calls = allowed, 0

    def ensure_legal_actor_usable(self, operation, mandate_id):
        self.calls += 1
        assert operation == OP
        assert mandate_id == "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d"
        if not self.allowed:
            raise LegalActorNotAuthorised("missing iDempiere invoice issuer readiness")


class TestLegalActorFinancialPEP(unittest.TestCase):
    def test_rechecks_on_each_mutation_and_replay(self):
        assessor, provider, calls = Assessor(decision()), NativeReadiness(), []
        for _ in range(2):
            out = perform_governed_financial_action(
                OP, assessor=assessor, provider=provider,
                execute=lambda: calls.append("posted") or "idempiere-posted",
                now=lambda: NOW,
            )
            self.assertEqual(out, "idempiere-posted")
        self.assertEqual((assessor.calls, provider.calls, len(calls)), (2, 2, 2))

    def test_denials_prevent_native_erp_mutation(self):
        cases = [
            {"context_id": "foreign-context"},
            {"operation_reference": "different-invoice"},
            {"provider_permissions_granted": True},
            {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "outcome": "REVOKED_OR_EXPIRED"}},
            {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "responsible_legal_entity_id": "LE-OTHER"}},
            {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "valid_until": (NOW - timedelta(seconds=1)).isoformat()}},
            {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "evaluated_at": (NOW - timedelta(minutes=2)).isoformat()}},
            {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "evidence_references": []}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                assessor, provider, calls = Assessor({**decision(), **changes}), NativeReadiness(), []
                with self.assertRaises(LegalActorNotAuthorised):
                    perform_governed_financial_action(
                        OP, assessor=assessor, provider=provider,
                        execute=lambda: calls.append("posted"), now=lambda: NOW)
                self.assertEqual(calls, [])
                self.assertEqual(provider.calls, 0)

    def test_provider_not_ready_denies_valid_cp_decision(self):
        assessor, provider, calls = Assessor(decision()), NativeReadiness(False), []
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                OP, assessor=assessor, provider=provider,
                execute=lambda: calls.append("posted"), now=lambda: NOW)
        self.assertEqual(calls, [])
        self.assertEqual((assessor.calls, provider.calls), (1, 1))

    def test_missing_actor_or_provider_never_uses_tenant_default(self):
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                replace(OP, expected_legal_entity_id=""), assessor=Assessor(decision()),
                provider=NativeReadiness(), execute=lambda: True, now=lambda: NOW)
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                OP, assessor=Assessor(decision()), provider=None,
                execute=lambda: True, now=lambda: NOW)

    def test_nabhold_is_only_a_proposed_za_actor_and_never_a_default(self):
        # Actual first-party identifiers are used to demonstrate DENIAL, not
        # to create a simulated verified Nabhold legal mandate or finance baseline.
        proposed = replace(OP, expected_legal_entity_id="NABHOLD")
        no_mandate = decision(outcome="NO_APPLICABLE_MANDATE")
        assessor, provider, calls = Assessor(no_mandate), NativeReadiness(), []
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                proposed, assessor=assessor, provider=provider,
                execute=lambda: calls.append("posted"), now=lambda: NOW,
            )
        self.assertEqual((assessor.calls, provider.calls, calls), (1, 0, []))

        # A ZA attribution must never leak into an unverified UG decision.
        ug = replace(proposed, market="UG")
        assessor, provider, calls = Assessor(no_mandate), NativeReadiness(), []
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                ug, assessor=assessor, provider=provider,
                execute=lambda: calls.append("posted"), now=lambda: NOW,
            )
        self.assertEqual((assessor.calls, provider.calls, calls), (1, 0, []))

    def test_cp_decision_is_not_itself_provider_approval(self):
        self.assertTrue(assert_current_decision(OP, decision(), now=NOW).endswith("a6d"))


if __name__ == "__main__":
    unittest.main()
