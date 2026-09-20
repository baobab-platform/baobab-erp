import unittest

from integration.business_partner_adapter import BusinessPartnerProjectionError
from application.business_partner_http import execute_project, parse_project_request


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 50

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


class BusinessPartnerHttpTests(unittest.TestCase):
    def test_parse_requires_roles(self):
        with self.assertRaises(BusinessPartnerProjectionError):
            parse_project_request(
                {
                    "engine_instance_id": "erp",
                    "legal_entity_id": "le",
                    "canonical_organisation_id": "org",
                    "display_name": "Co",
                    "readiness_status": "READY",
                    "roles": [],
                }
            )

    def test_execute_project_returns_public_payload(self):
        body = {
            "engine_instance_id": "erp",
            "legal_entity_id": "le_ug",
            "canonical_organisation_id": "org_1",
            "display_name": "Co-op",
            "readiness_status": "READY",
            "roles": ["supplier"],
            "billing_country": "UG",
        }
        out = execute_project(body, client=FakeClient(), mappings=FakeMappings())
        self.assertTrue(out["business_partner"]["business_partner_id"].startswith("erp_"))
        self.assertEqual(out["created"], 1)


if __name__ == "__main__":
    unittest.main()
