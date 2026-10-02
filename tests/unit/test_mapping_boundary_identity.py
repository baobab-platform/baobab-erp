import unittest
from datetime import datetime, timezone

from mapping import identifiers
from mapping.context import LegalEntityContext
from mapping.model import CanonicalReference, Mapping, MappingStatus

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _mapping(**overrides):
    base = dict(
        mapping_id="map_0123456789ab",
        tenant_id="tn_abc123",
        legal_entity_id="ZURIBEANS-ZA",
        canonical_reference=CanonicalReference("trade", "customer", "cust-1"),
        erp_resource_id="erp_0123456789ab",
        status=MappingStatus.ACTIVE,
        revision=1,
        effective_from=NOW,
    )
    base.update(overrides)
    return Mapping(**base)


class IdentifierGrammarTests(unittest.TestCase):
    def test_accepts_contract_forms(self):
        self.assertEqual(identifiers.tenant_id("tn_abc123"), "tn_abc123")
        self.assertEqual(identifiers.legal_entity_id("ZURIBEANS-ZA"), "ZURIBEANS-ZA")
        self.assertEqual(identifiers.mapping_id("map_0123456789ab"), "map_0123456789ab")
        self.assertEqual(identifiers.erp_resource_id("erp_0123456789ab"), "erp_0123456789ab")

    def test_rejects_names_vendor_ids_and_wrong_shapes(self):
        for bad in ("tenant-1", "tn_", "TN_ABC123", "tn_ABC123", "", None, 7):
            with self.assertRaises(identifiers.IdentifierError, msg=repr(bad)):
                identifiers.tenant_id(bad)
        for bad in ("zuribeans-za", "ZA", "Zuribeans Ltd", "-ZA-", "ZURI_BEANS"):
            with self.assertRaises(identifiers.IdentifierError, msg=repr(bad)):
                identifiers.legal_entity_id(bad)
        with self.assertRaises(identifiers.IdentifierError):
            identifiers.erp_resource_id("1001")  # a leaked iDempiere record id
        with self.assertRaises(identifiers.IdentifierError):
            identifiers.mapping_id("erp_0123456789ab")

    def test_minted_ids_satisfy_their_own_grammar(self):
        identifiers.mapping_id(identifiers.new_mapping_id())
        identifiers.erp_resource_id(identifiers.new_erp_resource_id())
        self.assertNotEqual(identifiers.new_mapping_id(), identifiers.new_mapping_id())


class LegalEntityContextTests(unittest.TestCase):
    def test_context_requires_an_explicit_valid_pair(self):
        ctx = LegalEntityContext("tn_abc123", "ZURIBEANS-ZA")
        self.assertEqual((ctx.tenant_id, ctx.legal_entity_id), ("tn_abc123", "ZURIBEANS-ZA"))
        with self.assertRaises(identifiers.IdentifierError):
            LegalEntityContext("tn_abc123", "zuribeans")
        with self.assertRaises(identifiers.IdentifierError):
            LegalEntityContext("tenant", "ZURIBEANS-ZA")

    def test_one_tenant_may_hold_several_legal_entities(self):
        a = LegalEntityContext("tn_abc123", "ZURIBEANS-ZA")
        b = LegalEntityContext("tn_abc123", "ZURIBEANS-UG")
        self.assertNotEqual(a, b)

    def test_port_exposes_no_tenant_to_legal_entity_lookup(self):
        from mapping.context import ControlPlaneContextPort

        self.assertEqual(
            [n for n in vars(ControlPlaneContextPort) if not n.startswith("_")], ["validate_context"]
        )


class MappingContractTests(unittest.TestCase):
    def test_public_mapping_carries_no_vendor_binding(self):
        body = _mapping().to_contract()
        self.assertEqual(
            set(body),
            {"mapping_id", "tenant_id", "legal_entity_id", "canonical_reference",
             "erp_resource_id", "status", "revision", "effective_from"},
        )
        self.assertNotIn("native_id", body)
        self.assertNotIn("native_table", body)
        self.assertEqual(body["canonical_reference"],
                         {"owner": "trade", "resource_type": "customer", "resource_id": "cust-1"})

    def test_optional_temporal_fields_only_when_present(self):
        body = _mapping(effective_to=NOW, replaces_mapping_id="map_aaaaaaaaaaaa").to_contract()
        self.assertIn("effective_to", body)
        self.assertEqual(body["replaces_mapping_id"], "map_aaaaaaaaaaaa")

    def test_unreconciled_mapping_is_not_publishable(self):
        for bad in (_mapping(legal_entity_id=None, status=MappingStatus.QUARANTINED),
                    _mapping(canonical_reference=None)):
            with self.assertRaises(ValueError):
                bad.to_contract()

    def test_status_values_match_the_contract(self):
        self.assertEqual(
            {s.value for s in MappingStatus},
            {"pending", "active", "suspended", "retired", "quarantined"},
        )


if __name__ == "__main__":
    unittest.main()
