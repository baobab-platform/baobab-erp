"""LA-05D acceptance: no native mutation without fresh CP + ERP authority."""
from datetime import datetime, timedelta, timezone
import pytest

from order_to_cash.legal_actor_gate import (
    LegalActorNotAuthorised, LegalActorOperation,
    assert_current_decision, perform_governed_financial_action,
)

_NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
_OPERATION = LegalActorOperation(
    context_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
    tenant_id="tn_testoperating", operating_organisation_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
    expected_legal_entity_id="LE-TEST-ISSUER",
    role="INVOICE_ISSUER", activity="B2B_COFFEE_INVOICE",
    market="ZA", capability="accounting.customer-invoice.post",
    operation_reference="invoice-123",
)


def decision(*, at=_NOW, until=None, outcome="AUTHORIZED"):
    return {
        "context_id": _OPERATION.context_id,
        "operation_reference": _OPERATION.operation_reference,
        "provider_permissions_granted": False,
        "legal_actor_resolution": {
            "outcome": outcome, "policy_reference": "ADR-BCP-027/LA-04B",
            "evaluated_at": at.isoformat(), "valid_until": (until or at + timedelta(seconds=20)).isoformat(),
            "mandate_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d",
            "responsible_legal_entity_id": "LE-TEST-ISSUER",
            "evidence_references": ["synthetic/official-reference"],
        },
    }


class Assessor:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def assess(self, request):
        self.calls += 1
        assert request == {
            "context_id": _OPERATION.context_id,
            "role": _OPERATION.role,
            "activity": _OPERATION.activity,
            "market": _OPERATION.market,
            "capability": _OPERATION.capability,
            "operation_reference": _OPERATION.operation_reference,
        }
        return self.value


class NativeReadiness:
    def __init__(self, allowed=True):
        self.allowed, self.calls = allowed, 0

    def ensure_legal_actor_usable(self, operation, mandate_id):
        self.calls += 1
        assert operation == _OPERATION
        assert mandate_id == "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6d"
        if not self.allowed:
            raise LegalActorNotAuthorised("missing iDempiere invoice issuer readiness")


def test_governed_invoice_action_rechecks_on_every_mutation_and_replay():
    assessor, provider, calls = Assessor(decision()), NativeReadiness(), []
    def execute():
        calls.append("posted")
        return "idempiere-posted"
    for _ in range(2):
        assert perform_governed_financial_action(
            _OPERATION, assessor=assessor, provider=provider,
            execute=execute, now=lambda: _NOW) == "idempiere-posted"
    assert assessor.calls == provider.calls == len(calls) == 2


@pytest.mark.parametrize("alter", [
    {"context_id": "foreign-context"},
    {"operation_reference": "different-invoice"},
    {"provider_permissions_granted": True},
    {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "outcome": "REVOKED_OR_EXPIRED"}},
    {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "responsible_legal_entity_id": "LE-OTHER"}},
    {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "valid_until": (_NOW - timedelta(seconds=1)).isoformat()}},
    {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "evaluated_at": (_NOW - timedelta(minutes=2)).isoformat()}},
    {"legal_actor_resolution": {**decision()["legal_actor_resolution"], "evidence_references": []}},
])
def test_denials_prevent_native_erp_mutation(alter):
    assessor, provider, calls = Assessor({**decision(), **alter}), NativeReadiness(), []
    with pytest.raises(LegalActorNotAuthorised):
        perform_governed_financial_action(
            _OPERATION, assessor=assessor, provider=provider,
            execute=lambda: calls.append("posted"), now=lambda: _NOW)
    assert calls == [] and provider.calls == 0


def test_native_provider_not_ready_denies_even_when_cp_authorized():
    assessor, provider, calls = Assessor(decision()), NativeReadiness(allowed=False), []
    with pytest.raises(LegalActorNotAuthorised):
        perform_governed_financial_action(
            _OPERATION, assessor=assessor, provider=provider,
            execute=lambda: calls.append("posted"), now=lambda: _NOW)
    assert calls == [] and assessor.calls == provider.calls == 1


def test_missing_actor_or_provider_is_never_inferred_from_default_tenant():
    from dataclasses import replace
    with pytest.raises(LegalActorNotAuthorised):
        perform_governed_financial_action(replace(_OPERATION, expected_legal_entity_id=""),
                                         assessor=Assessor(decision()), provider=NativeReadiness(),
                                         execute=lambda: True, now=lambda: _NOW)
    with pytest.raises(LegalActorNotAuthorised):
        perform_governed_financial_action(_OPERATION, assessor=Assessor(decision()),
                                         provider=None, execute=lambda: True, now=lambda: _NOW)


def test_pure_decision_cannot_become_own_provider_approval():
    assert assert_current_decision(_OPERATION, decision(), now=_NOW).endswith("a6d")
