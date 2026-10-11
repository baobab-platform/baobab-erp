"""LA-05D5 synthetic negative matrix; does not certify a real ERP provider."""
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from order_to_cash.legal_actor_gate import LegalActorNotAuthorised, LegalActorOperation
from order_to_cash.model import TenantScope
from order_to_cash.service import _deny_legacy_native_action
from order_to_cash.native_action_gate import NativeActionPolicy, perform_governed_native_action

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
SCOPE = TenantScope("tn-zuribeans-fixture", "LE-SYNTHETIC-ISSUER", 9, 0)
ROLES = {
    "create_sales_order": "CONTRACTING_PARTY",
    "complete_sales_order": "CONTRACTING_PARTY",
    "create_shipment": "CONTRACTING_PARTY",
    "complete_shipment": "CONTRACTING_PARTY",
    "create_customer_invoice": "INVOICE_ISSUER",
    "create_payment": "ACCOUNTING_ENTITY",
    "complete_payment": "ACCOUNTING_ENTITY",
    "allocate_payment": "ACCOUNTING_ENTITY",
}

class Assessor:
    def __init__(self):
        self.calls = 0
        self.deny_second = False
    def assess(self, request):
        self.calls += 1
        outcome = "REVOKED_OR_EXPIRED" if self.deny_second and self.calls == 2 else "AUTHORIZED"
        return {
            "context_id": request["context_id"],
            "operation_reference": request["operation_reference"],
            "provider_permissions_granted": False,
            "legal_actor_resolution": {
                "outcome": outcome, "mandate_id": "mandate-synthetic-reviewed",
                "responsible_legal_entity_id": SCOPE.legal_entity_id,
                "evidence_references": ["synthetic/evidence/independent"],
                "evaluated_at": NOW.isoformat(),
                "valid_until": (NOW+timedelta(seconds=12)).isoformat(),
            }
        }

class Provider:
    def __init__(self): self.calls = 0
    def ensure_legal_actor_usable(self, operation, mandate):
        self.calls += 1
        assert mandate == "mandate-synthetic-reviewed"

class Documentary:
    def __init__(self, blocked=False):
        self.calls = 0
        self.blocked = blocked
    def assess(self, request):
        self.calls += 1
        return {
            **request,
            "organisation_id": "org-fixture",
            "blocked": self.blocked,
            "authority_granted": False,
            "policy_reference": "ADR-BCP-026/negative-only",
            "evaluated_at": NOW.isoformat(),
            "expires_at": (NOW+timedelta(seconds=1)).isoformat(),
        }

def inputs(action):
    reference = "native-operation-" + action
    capability = "synthetic.test-only." + action
    policy = NativeActionPolicy(
        action=action, activity="B2B_ACCOUNTING",
        capability=capability, authority_reference="synthetic/shared-provider-census",
    )
    operation = LegalActorOperation(
        context_id="ctx-fixture-verified-by-cp",
        tenant_id=SCOPE.tenant_id,
        operating_organisation_id="org-fixture",
        expected_legal_entity_id=SCOPE.legal_entity_id,
        role=ROLES[action], activity=policy.activity, market="ZA",
        capability=capability, operation_reference=reference,
    )
    return policy, operation, reference

class NativeActionGateTests(unittest.TestCase):
    def test_all_legacy_native_mutations_fail_closed_before_mapping_or_provider(self):
        with patch.dict(os.environ, {"BAOBAB_DEPLOYMENT_ENV":"staging"}):
            for action in ROLES:
                policy,operation,ref = inputs(action)
                with self.subTest(action=action), self.assertRaises(Exception):
                    _deny_legacy_native_action(SCOPE, action, ref)

    def test_per_action_per_resource_per_tenant_per_legal_actor_ephemeral_guard(self):
        with patch.dict(os.environ, {"BAOBAB_DEPLOYMENT_ENV":"production"}):
            for action in ROLES:
                policy,operation,reference=inputs(action)
                assessor,provider,documentary=Assessor(),Provider(),Documentary()
                called=[]
                def native():
                    _deny_legacy_native_action(SCOPE,action,reference)
                    for forbidden in ("create_payment","complete_sales_order"):
                        if forbidden != action:
                            with self.assertRaises(Exception):
                                _deny_legacy_native_action(SCOPE,forbidden,reference)
                    with self.assertRaises(Exception):
                        _deny_legacy_native_action(SCOPE,action,"different-native-id")
                    with self.assertRaises(Exception):
                        _deny_legacy_native_action(
                            TenantScope("tn-other",SCOPE.legal_entity_id,9,0),action,reference)
                    with self.assertRaises(Exception):
                        _deny_legacy_native_action(
                            TenantScope(SCOPE.tenant_id,"LE-OTHER",9,0),action,reference)
                    called.append(action)
                perform_governed_native_action(
                    policy=policy,operation=operation,scope=SCOPE,
                    resource_reference=reference,assessor=assessor,
                    provider=provider,documentary=documentary,execute=native,now=lambda:NOW,
                )
                self.assertEqual(called,[action])
                self.assertEqual((assessor.calls,provider.calls,documentary.calls),(2,1,2))
                with self.assertRaises(Exception):
                    _deny_legacy_native_action(SCOPE,action,reference)

    def test_unapproved_policy_mismatch_or_documentary_veto_never_runs_native(self):
        action="complete_payment"
        policy,operation,reference=inputs(action)
        variants=[
            {"policy":None},
            {"operation":replace(operation,role="INVOICE_ISSUER")},
            {"operation":replace(operation,tenant_id="tn-foreign")},
            {"operation":replace(operation,expected_legal_entity_id="LE-FOREIGN")},
            {"operation":replace(operation,capability="inventory.write")},
            {"operation":replace(operation,operation_reference="another-payment")},
            {"policy":replace(policy,authority_reference="")},
            {"policy":replace(policy,action="unsupported_payment_write")},
            {"documentary":None},
            {"documentary":Documentary(blocked=True)},
        ]
        for variant in variants:
            called=[]
            params=dict(policy=policy,operation=operation,scope=SCOPE,
                resource_reference=reference,assessor=Assessor(),provider=Provider(),
                documentary=Documentary(),execute=lambda:called.append("illegal"),now=lambda:NOW)
            params.update(variant)
            with self.subTest(variant=variant),self.assertRaises(LegalActorNotAuthorised):
                perform_governed_native_action(**params)
            self.assertEqual(called,[])

    def test_revocation_at_last_point_of_use(self):
        policy,op,ref=inputs("complete_shipment")
        assessor=Assessor();assessor.deny_second=True
        called=[]
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_native_action(policy=policy,operation=op,scope=SCOPE,
                resource_reference=ref,assessor=assessor,provider=Provider(),
                documentary=Documentary(),execute=lambda:called.append("illegal"),now=lambda:NOW)
        self.assertEqual(called,[])

if __name__ == "__main__":
    unittest.main()
