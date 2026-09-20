import unittest

from integration.business_partner_adapter import (
    BusinessPartnerProjectionError,
    BusinessPartnerProjectionRequest,
    mint_public_business_partner_id,
    project_business_partner,
)


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 100

    def create_record(self, table, fields):
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def update_record(self, table, record_id, fields):
        self.records[(table, record_id)].update(fields)


class FakeMappings:
    def __init__(self):
        self.values = {}

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        return self.values.get((engine_instance_id, legal_entity_id, kind, canonical_id))

    def put(self, *, engine_instance_id, legal_entity_id, kind, canonical_id, native_id, desired_digest, source_version):
        self.values[(engine_instance_id, legal_entity_id, kind, canonical_id)] = (
            native_id,
            desired_digest,
            source_version,
        )


def supplier_request(**overrides) -> BusinessPartnerProjectionRequest:
    defaults = dict(
        engine_instance_id="erp-zuribeans",
        legal_entity_id="le_zuribeans_ug",
        canonical_organisation_id="org_supplier_cooperative_1",
        display_name="Uganda Coffee Cooperative",
        readiness_status="READY",
        roles=("supplier",),
        billing_country="UG",
        default_currency="UGX",
        source_version="1",
    )
    defaults.update(overrides)
    return BusinessPartnerProjectionRequest(**defaults)


class BusinessPartnerAdapterTests(unittest.TestCase):
    def test_fails_closed_when_not_ready(self):
        client, mappings = FakeClient(), FakeMappings()
        with self.assertRaises(BusinessPartnerProjectionError) as ctx:
            project_business_partner(
                supplier_request(readiness_status="NOT_REQUESTED"),
                client=client,
                mappings=mappings,
            )
        self.assertIn("READY", str(ctx.exception))
        self.assertEqual(len(client.records), 0)

    def test_projects_supplier_to_c_bpartner(self):
        client, mappings = FakeClient(), FakeMappings()
        result = project_business_partner(supplier_request(), client=client, mappings=mappings)

        self.assertEqual(result.created, 1)
        self.assertEqual(result.native_table, "C_BPartner")
        self.assertIsNotNone(result.native_record_id)
        fields = client.records[("C_BPartner", result.native_record_id)]
        self.assertEqual(fields["Name"], "Uganda Coffee Cooperative")
        self.assertTrue(fields["IsVendor"])
        self.assertFalse(fields["IsCustomer"])

        public = result.projection.to_public_dict()
        self.assertTrue(public["business_partner_id"].startswith("erp_"))
        self.assertNotIn("C_BPartner", public["business_partner_id"])
        self.assertEqual(public["roles"], ["supplier"])
        self.assertEqual(public["billing_country"], "UG")
        self.assertEqual(public["status"], "active")

    def test_idempotent_reproject_reuses_native_row(self):
        client, mappings = FakeClient(), FakeMappings()
        first = project_business_partner(supplier_request(), client=client, mappings=mappings)
        second = project_business_partner(supplier_request(), client=client, mappings=mappings)
        self.assertEqual(first.created, 1)
        self.assertEqual(second.reused, 1)
        self.assertEqual(len(client.records), 1)
        self.assertEqual(
            first.projection.business_partner_id,
            second.projection.business_partner_id,
        )

    def test_public_id_is_stable_and_not_native(self):
        a = mint_public_business_partner_id(
            legal_entity_id="le_zuribeans_ug",
            canonical_organisation_id="org_1",
        )
        b = mint_public_business_partner_id(
            legal_entity_id="le_zuribeans_ug",
            canonical_organisation_id="org_1",
        )
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("erp_bp"))

    def test_rejects_empty_roles(self):
        with self.assertRaises(BusinessPartnerProjectionError):
            supplier_request(roles=()).validate()

    def test_projects_buyer_as_customer_and_preserves_trade_identity(self):
        client, mappings = FakeClient(), FakeMappings()
        request = supplier_request(
            canonical_organisation_id="org_buyer_1",
            display_name="Cape Coffee Buyers",
            roles=("customer",),
            billing_country="ZA",
            default_currency="ZAR",
            source_customer_id="buyerorg_cape1",
        )

        result = project_business_partner(request, client=client, mappings=mappings)

        fields = client.records[("C_BPartner", result.native_record_id)]
        self.assertTrue(fields["IsCustomer"])
        self.assertFalse(fields["IsVendor"])
        public = result.projection.to_public_dict()
        self.assertEqual(public["source_customer_id"], "buyerorg_cape1")
        self.assertEqual(public["default_currency"], "ZAR")

    def test_same_canonical_party_is_isolated_per_legal_entity(self):
        client, mappings = FakeClient(), FakeMappings()
        ug = project_business_partner(
            supplier_request(
                canonical_organisation_id="org_buyer_shared",
                roles=("customer",),
                source_customer_id="buyerorg_shared",
            ),
            client=client,
            mappings=mappings,
        )
        za = project_business_partner(
            supplier_request(
                canonical_organisation_id="org_buyer_shared",
                legal_entity_id="le_zuribeans_za",
                billing_country="ZA",
                default_currency="ZAR",
                roles=("customer",),
                source_customer_id="buyerorg_shared",
            ),
            client=client,
            mappings=mappings,
        )

        self.assertEqual(ug.created, 1)
        self.assertEqual(za.created, 1)
        self.assertNotEqual(
            ug.projection.business_partner_id,
            za.projection.business_partner_id,
        )
        self.assertEqual(len(client.records), 2)


if __name__ == "__main__":
    unittest.main()
