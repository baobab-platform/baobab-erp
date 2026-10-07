"""ERP API 1.1 authority, CP validation wire shape and replay semantics at the exact Shared pin."""
import unittest

import _shared as shared
from application import boundary
from provisioning.operation_request import RequestError, parse_command
from security.platform_context import ContextUnavailable, validated_tenant

CONTEXT = "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b"
TENANT = "tn_01k4zuribeans"


class ContextAuthorityConformanceTests(unittest.TestCase):
    def test_only_the_four_contract_operations_require_cp_context_authority(self):
        routes = [("POST", "/provisioning-operations", True), ("GET", "/provisioning-operations/x", True),
                  ("GET", "/order-consequences/x", True), ("GET", "/inventory-availability", True),
                  ("GET", "/mappings", False), ("GET", "/mappings/x", False)]
        for method, path, required in routes:
            self.assertEqual(boundary.match(method, path).context_required, required)
        for path in ("/provisioning-operations/{operation_id}", "/order-consequences/{commerce_order_id}",
                     "/inventory-availability"):
            parameters = shared._OPENAPI["paths"][path]["get"]["parameters"]
            # Context parameters may be factored into the OpenAPI components.
            self.assertTrue(any(p.get("name") == "context_id" or "ContextId" in p.get("$ref", "")
                                for p in parameters), path)

    def test_cp_validator_response_requires_expiry_and_rejects_invented_legal_entity(self):
        schema = shared.schema_uri("control-plane/v1/platform-context.schema.json", "/$defs/PlatformContextValidation")
        answer = {"context_id": CONTEXT, "tenant_id": TENANT,
                  "resolved_at": "2020-01-01T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z"}
        self.assertEqual(shared.errors(schema, answer), [])
        self.assertEqual(validated_tenant(answer, CONTEXT), TENANT)
        for patch in ({"expires_at": None}, {"legal_entity_id": "ZURIBEANS-ZA"}, {"organisation_type": "x"}):
            body = dict(answer, **patch)
            self.assertNotEqual(shared.errors(schema, body), [])
            with self.assertRaises(ContextUnavailable):
                validated_tenant(body, CONTEXT)

    def test_provisioning_context_is_required_but_does_not_change_the_request_fingerprint(self):
        schema = shared.schema_uri("erp/v1/provisioning-request.schema.json")
        body = {"context_id": CONTEXT, "tenant_id": TENANT, "legal_entity_ids": ["ZURIBEANS-ZA"],
                "requested_countries": ["ZA"], "functional_currencies": ["ZAR"],
                "control_plane_authority": {"tenant_provisioning_id": "tp_0199a1b2c3d47e8f",
                                            "plan_id": "plan_0199a1b2c3d47e8f", "plan_version": 1,
                                            "plan_digest": "sha256:" + "ab" * 32}}
        self.assertEqual(shared.errors(schema, body), [])
        original = parse_command(body)
        fresh = parse_command(dict(body, context_id="0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c"))
        self.assertEqual(original.fingerprint("caller"), fresh.fingerprint("caller"))
        self.assertNotEqual(original.fingerprint("caller"), fresh.fingerprint("other-caller"))
        missing = {k: v for k, v in body.items() if k != "context_id"}
        self.assertNotEqual(shared.errors(schema, missing), [])
        with self.assertRaises(RequestError):
            parse_command(missing)


if __name__ == "__main__":
    unittest.main()
