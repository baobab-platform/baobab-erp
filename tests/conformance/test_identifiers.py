"""The identifier grammars ERP enforces are the ones Shared defines, not look-alikes."""

import unittest

import _shared as shared
from events.cloudevent import _IDEMPOTENCY, _TRACEPARENT, _TYPE
from mapping import identifiers


def _pattern(path: str, name: str) -> str:
    return shared.read_json(path)["$defs"][name]["pattern"]


class IdentifierGrammarTests(unittest.TestCase):
    def test_patterns_equal_shared(self):
        cases = {
            "tenant_id": (identifiers._TENANT_ID, "control-plane/v1/domain.schema.json", "tenantId"),
            "legal_entity_id": (identifiers._LEGAL_ENTITY_ID, "control-plane/v1/domain.schema.json", "canonicalLegalEntityId"),
            "mapping_id": (identifiers._MAPPING_ID, "erp/v1/domain.schema.json", "mappingId"),
            "erp_resource_id": (identifiers._ERP_RESOURCE_ID, "erp/v1/domain.schema.json", "erpResourceId"),
        }
        for name, (compiled, path, definition) in cases.items():
            with self.subTest(name):
                shared_pattern = _pattern(path, definition)
                self.assertEqual(compiled.pattern, shared_pattern)

    def test_event_member_patterns_equal_shared(self):
        props = shared.read_json("events/v1/envelope.schema.json")["properties"]
        self.assertEqual(_TYPE.pattern, props["type"]["pattern"])
        self.assertEqual(_IDEMPOTENCY.pattern, props["idempotencykey"]["pattern"])
        self.assertEqual(_TRACEPARENT.pattern, props["traceparent"]["pattern"])

    def test_length_bounds_match_shared(self):
        defs = shared.read_json("control-plane/v1/domain.schema.json")["$defs"]
        self.assertEqual((defs["tenantId"]["minLength"], defs["tenantId"]["maxLength"]), (6, 63))
        self.assertEqual((defs["canonicalLegalEntityId"]["minLength"], defs["canonicalLegalEntityId"]["maxLength"]), (3, 63))
        erp = shared.read_json("erp/v1/domain.schema.json")["$defs"]
        self.assertEqual((erp["mappingId"]["minLength"], erp["mappingId"]["maxLength"]), (8, 63))
        self.assertEqual((erp["erpResourceId"]["minLength"], erp["erpResourceId"]["maxLength"]), (8, 63))
        # the code enforces exactly those bounds
        identifiers.tenant_id("tn_" + "a" * 3)
        with self.assertRaises(identifiers.IdentifierError):
            identifiers.tenant_id("tn_" + "a" * 2)
        with self.assertRaises(identifiers.IdentifierError):
            identifiers.tenant_id("tn_" + "a" * 61)

    def test_minted_ids_validate_against_shared(self):
        shared.validate(shared.schema_uri("erp/v1/domain.schema.json", "/$defs/mappingId"), identifiers.new_mapping_id())
        shared.validate(shared.schema_uri("erp/v1/domain.schema.json", "/$defs/erpResourceId"), identifiers.new_erp_resource_id())


if __name__ == "__main__":
    unittest.main()
