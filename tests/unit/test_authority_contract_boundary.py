"""Wire-valid is not authorised; injected ports must never bypass canonical facts."""
import copy
import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from order_to_cash.documentary_restriction import assert_documentary_scope_unblocked
from order_to_cash.legal_actor_gate import (
    LegalActorNotAuthorised, LegalActorOperation, perform_governed_financial_action,
)
from order_to_cash.legal_actor_http_client import HttpControlPlaneLegalActorAssessor
from provisioning.control_plane_client import ControlPlaneUnavailable, HttpControlPlaneAssignmentSource
from shared_contracts import validate_contract

CASES = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/authority-contract-cases.json').read_bytes())
LEGAL = next(c['instance'] for c in CASES if c['name'] == 'legal_response/valid')
DOC = next(c['instance'] for c in CASES if c['name'] == 'documentary_response/valid')
REQUEST = next(c['instance'] for c in CASES if c['name'] == 'legal_request/valid')
NOW = datetime(2026, 10, 13, 4, tzinfo=timezone.utc)
OP = LegalActorOperation(
    context_id=REQUEST['context_id'], tenant_id='tn_synthetic', operating_organisation_id=DOC['organisation_id'],
    expected_legal_entity_id=LEGAL['legal_actor_resolution']['responsible_legal_entity_id'],
    role=REQUEST['role'], activity=REQUEST['activity'], market=REQUEST['market'],
    capability=REQUEST['capability'], operation_reference=REQUEST['operation_reference'],
)


class ConsequentialContractBoundaryTests(unittest.TestCase):
    def denied_before_provider(self, result):
        provider, execute = Mock(), Mock()
        with self.assertRaises(LegalActorNotAuthorised):
            perform_governed_financial_action(
                OP, assessor=Mock(assess=Mock(return_value=result)), provider=provider,
                execute=execute, now=lambda: NOW,
            )
        provider.ensure_legal_actor_usable.assert_not_called()
        execute.assert_not_called()

    def test_injected_malformed_or_canonical_denied_decisions_never_reach_native_provider(self):
        for case in CASES:
            if case['contract'] == 'legal_response' and (not case['valid'] or '/denial/' in case['name']):
                with self.subTest(case=case['name']):
                    self.denied_before_provider(case['instance'])

    def test_valid_wire_still_denies_scope_actor_and_freshness_mismatches(self):
        for patch in [
            {'operation_reference': 'synthetic/another-operation'},
            {'context_id': '0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a7b'},
            {'legal_actor_resolution': {**LEGAL['legal_actor_resolution'], 'responsible_legal_entity_id': 'LE-FOREIGN'}},
            {'legal_actor_resolution': {**LEGAL['legal_actor_resolution'], 'valid_until': '2026-10-13T03:59:59Z'}},
        ]:
            value = {**copy.deepcopy(LEGAL), **patch}
            validate_contract('legal_response', value)
            self.denied_before_provider(value)

    def test_injected_documentary_wire_corruption_denies_before_scope_can_clear(self):
        for case in CASES:
            if case['contract'] == 'documentary_response' and not case['valid']:
                with self.subTest(case=case['name']), self.assertRaises(LegalActorNotAuthorised):
                    assert_documentary_scope_unblocked(OP, case['instance'], now=NOW)

    def test_invalid_canonical_request_is_denied_before_iam_or_transport(self):
        token, correlation, opener = Mock(), Mock(), Mock()
        client = HttpControlPlaneLegalActorAssessor('https://cp.example.invalid', token, correlation, opener=opener)
        for patch in [{'context_id': 'ctx-local-fiction'}, {'role': 'TRUST_ME'}, {'activity': 'x' * 161}, {'operation_reference': 'x' * 501}, {'grant': True}]:
            with self.assertRaises(ControlPlaneUnavailable):
                client.assess({**REQUEST, **patch})
        token.assert_not_called()
        correlation.assert_not_called()
        opener.open.assert_not_called()


class AssignmentWireTransportTests(unittest.TestCase):
    def test_valid_assignment_and_duplicate_or_oversized_facts(self):
        body = next(c['instance'] for c in CASES if c['name'] == 'erp_assignment/valid')
        wire = json.dumps(body).encode()
        tenant = json.dumps(body['tenant_id']).encode()
        key = b'"tenant_id": ' + tenant
        duplicate = wire.replace(key, key + b', ' + key)
        for raw, valid in [(wire, True), (duplicate, False), (b' ' * 65537, False)]:
            opener = Mock(open=Mock(return_value=io.BytesIO(raw)))
            source = HttpControlPlaneAssignmentSource('https://cp.example.invalid', lambda: 'synthetic-token', opener=opener)
            args = dict(tenant_id=body['tenant_id'], tenant_provisioning_id=body['tenant_provisioning_id'],
                        legal_entity_id=body['legal_entity']['legal_entity_id'])
            if valid:
                self.assertEqual(source.resolve_erp_assignment(**args).tenant_id, body['tenant_id'])
                request = opener.open.call_args.args[0]
                self.assertEqual(request.get_header('Cache-control'), 'no-store')
            else:
                with self.assertRaises(ControlPlaneUnavailable):
                    source.resolve_erp_assignment(**args)
