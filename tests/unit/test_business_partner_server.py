import unittest

from application.server import _WORKLOAD_REQUIRED_SCOPES, make_handler


class DummyConfig:
    workload_oidc_issuer = "https://iam.example/realms/baobab"
    workload_oidc_audience = "baobab-erp"


class BusinessPartnerServerWiringTests(unittest.TestCase):
    def test_projection_route_is_deny_by_default_workload_surface(self):
        self.assertEqual(
            _WORKLOAD_REQUIRED_SCOPES["/business-partners/project"],
            "erp:integrate",
        )

    def test_projection_handler_is_wired_into_server_handler(self):
        handler = make_handler(DummyConfig(), key_resolver=object())
        self.assertTrue(hasattr(handler, "_handle_project_business_partner"))


if __name__ == "__main__":
    unittest.main()
