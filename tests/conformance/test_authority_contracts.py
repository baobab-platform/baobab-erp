"""P0-04A compares each runtime to its owner; copies agreeing is insufficient.

All vectors are synthetic wire compatibility tests, not accepted legal or native
posting evidence. Semantic scope/freshness denial tests remain independent.
"""
import hashlib
import importlib.util
import json
import unittest

import _shared as shared
from shared_contracts import PROVENANCE, ContractViolation, validate_contract

ROOT = shared.REPO
CASES = json.loads((ROOT / 'tests/fixtures/authority-contract-cases.json').read_bytes())


class AuthorityConformanceTests(unittest.TestCase):
    def test_complete_bundles_match_immutable_git_blobs_and_have_no_stale_files(self):
        spec = importlib.util.spec_from_file_location('sync', ROOT / 'scripts/sync_authority_contracts.py')
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        owned = sync.generate(shared.ROOT)
        for target in sync.TARGETS:
            actual = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(actual, owned)
        self.assertEqual(PROVENANCE['commit'], shared.PIN)
        self.assertEqual(PROVENANCE['repository'], shared.LOCK['source']['repository'])
        for path, digest in PROVENANCE['files'].items():
            self.assertEqual((shared.ROOT / path).read_bytes(), owned[path], 'owner checkout differs from immutable Git blob')
            self.assertIn(path, shared.LOCK['contracts'])
            self.assertEqual(hashlib.sha256(owned[path]).hexdigest(), digest)

    def test_every_wire_vector_agrees_with_shared_and_python_formats(self):
        for case in CASES:
            with self.subTest(case=case['name']):
                uri = PROVENANCE['entries'][case['contract']]
                self.assertEqual(not shared.errors(uri, case['instance']), case['valid'], 'owner disagreement')
                if case['valid']:
                    validate_contract(case['contract'], case['instance'])
                else:
                    with self.assertRaises(ContractViolation):
                        validate_contract(case['contract'], case['instance'])

    def test_workload_admission_is_not_granted_by_convergence(self):
        profiles = shared.read_yaml('identity/v1/workload-registry.yaml')['workloads']
        staging = profiles['baobab-erp-legal-actor-assessor-staging']
        self.assertEqual(staging['status'], 'PROVISIONED')
        self.assertEqual(staging['context_purposes'], ['RUNTIME'])
        self.assertEqual(set(staging['allowed_scopes']), {'context:resolve', 'legal-actor:assess',
                                                          'documentary:restriction-assess',
                                                          'erp-posting-authority:resolve'})
        production = profiles['baobab-erp-workload']
        self.assertEqual(production['status'], 'ACTIVE')
        for scope in ['legal-actor:assess', 'documentary:restriction-assess', 'erp-posting-authority:resolve']:
            self.assertNotIn(scope, production['allowed_scopes'])
