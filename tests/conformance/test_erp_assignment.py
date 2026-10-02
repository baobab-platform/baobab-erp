"""ERP's reading of the Control Plane ERP assignment, held to the Shared contract at the pin.

ERP parses Shared's ErpAssignment with its own closed-member parser (the runtime carries no JSON Schema engine). These
tests keep that parser, and the vocabularies ERP decides against, from drifting from the contract."""
import copy
import unittest

import _shared as shared
from provisioning.cp_contract import ERP_ENGINE_ID, AssignmentError, assignment_from_payload
from provisioning.validation import _MARKET_CAPABILITIES, ISOLATION_REQUIREMENTS, SUPPORTED_CAPABILITIES

SCHEMA = shared.schema_uri("control-plane/v1/erp-assignment.schema.json", "/$defs/ErpAssignment")
EXAMPLE = shared.read_json("control-plane/v1/examples/erp-assignment.json")
# Members Shared deliberately does not project: Control Plane registry identifiers stay internal, and native placement,
# accounting and per-market configuration are ERP-owned.
NOT_PROJECTED = ("capability_binding_id", "capability_bindings", "isolation_profile_id", "native_client_mode",
                 "native_client_key", "legal_entity_code", "target_environment", "currencies",
                 "localisation_profile", "warehouse_codes")


class ErpAssignmentConformanceTests(unittest.TestCase):
    def test_shared_publishes_a_valid_example(self):
        self.assertEqual(shared.errors(SCHEMA, EXAMPLE), [])

    def test_erp_parses_what_shared_publishes(self):
        assignment = assignment_from_payload(EXAMPLE)
        self.assertEqual(assignment.tenant_id, EXAMPLE["tenant_id"])
        self.assertEqual(assignment.legal_entity_id, EXAMPLE["legal_entity"]["legal_entity_id"])
        self.assertEqual(assignment.capabilities, frozenset(EXAMPLE["capabilities"]))
        self.assertEqual(assignment.engine_id, ERP_ENGINE_ID)

    def test_shared_and_erp_agree_on_every_member_that_is_not_projected(self):
        for field in NOT_PROJECTED:
            with self.subTest(field):
                top = {**copy.deepcopy(EXAMPLE), field: "x"}
                self.assertNotEqual(shared.errors(SCHEMA, top), [], "Shared accepts it")
                with self.assertRaises(AssignmentError):
                    assignment_from_payload(top)

    def test_shared_and_erp_agree_on_every_required_member(self):
        for field in EXAMPLE:
            with self.subTest(field):
                body = {k: v for k, v in copy.deepcopy(EXAMPLE).items() if k != field}
                self.assertNotEqual(shared.errors(SCHEMA, body), [], "Shared accepts it")
                with self.assertRaises(AssignmentError):
                    assignment_from_payload(body)

    def test_the_engine_erp_accepts_is_the_engine_shared_registers_for_its_capabilities(self):
        capabilities = shared.read_yaml("erp/v1/capabilities.yaml")["capabilities"]
        self.assertEqual({c["owner"] for c in capabilities}, {ERP_ENGINE_ID})

    def test_every_capability_erp_supports_is_one_shared_registers_for_erp(self):
        registered = {c["capability_key"] for c in shared.read_yaml("erp/v1/capabilities.yaml")["capabilities"]}
        self.assertLessEqual(SUPPORTED_CAPABILITIES, registered)

    def test_the_isolation_vocabulary_is_shared_s(self):
        enum = shared.read_json("admission/v1/decision.schema.json")["$defs"]["isolationStrategy"]["enum"]
        self.assertEqual(set(ISOLATION_REQUIREMENTS), set(enum))

    def test_the_market_participation_vocabulary_is_shared_s(self):
        enum = shared.read_json("control-plane/v1/domain.schema.json")["$defs"]["marketParticipationCapability"]["enum"]
        self.assertEqual(set(_MARKET_CAPABILITIES), {value.lower() for value in enum})


if __name__ == "__main__":
    unittest.main()
