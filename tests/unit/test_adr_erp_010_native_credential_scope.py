"""ADR-ERP-010: never authenticate to another native Client/Organization.

This test checks configuration and the actual legacy O2C client selector.
There is no faked success or CP authority: mismatched login is unusable.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from application.server import _load_idempiere_credentials, make_handler
from integration.idempiere_client import (
    IdempiereClientError, IdempiereCredentials, RestIdempiereClient,
)


def _credentials(client: int, org: int) -> IdempiereCredentials:
    return IdempiereCredentials(
        base_url="https://idempiere.internal/api/v1",
        username="erp-operator",
        password="test-only",
        client_id=client,
        role_id=101,
        organization_id=org,
    )


class NativeCredentialScopeTests(TestCase):
    def test_configuration_rejects_alias_and_cross_client_bindings(self):
        for payload in (
            {"100": {"client_id": 101}},  # wrong login for requested company
            {"0100": {"client_id": 100}},  # ambiguous spelling
            {"0": {"client_id": 0}},     # native System Client
            {"-100": {"client_id": -100}},
            ["not", "a", "mapping"],
            {"100": {"client_id": 100}, "0100": {"client_id": 100}},
        ):
            with self.subTest(payload=payload):
                with patch.dict(os.environ, {"IDEMPIERE_CLIENT_CREDENTIALS_JSON": json.dumps(payload)}):
                    with self.assertRaises((RuntimeError, ValueError, TypeError)):
                        _load_idempiere_credentials()

    def test_valid_configuration_preserves_client_and_role(self):
        fields = {"base_url": "https://idempiere.internal/api/v1",
                  "username": "local", "password": "test-only",
                  "client_id": 100, "role_id": 200, "organization_id": 300}
        with patch.dict(os.environ, {"IDEMPIERE_CLIENT_CREDENTIALS_JSON": json.dumps({"100": fields})}):
            credentials = _load_idempiere_credentials()
        self.assertEqual(set(credentials), {100})
        self.assertEqual(credentials[100].organization_id, 300)

    def test_injected_cross_client_and_cross_org_credentials_never_issue_native_calls(self):
        for mapping, requested_client, requested_org in (
            ({100: _credentials(200, 3)}, 100, 3),
            ({100: _credentials(100, 4)}, 100, 3),
            ({100: _credentials(100, 3)}, 100, 0),
            ({0: _credentials(0, 0)}, 0, 0),
        ):
            with self.subTest(client=requested_client, org=requested_org):
                config = SimpleNamespace(
                    workload_oidc_issuer="https://iam.invalid/realms/baobab",
                    idempiere_credentials_by_ad_client=mapping,
                )
                handler = make_handler(config)
                native = handler._build_idempiere_client(None, requested_client, requested_org)
                self.assertNotIsInstance(native, RestIdempiereClient)
                with self.assertRaises(IdempiereClientError):
                    native.get_record("C_Invoice", 1)

    def test_exact_native_context_preserves_native_client(self):
        config = SimpleNamespace(
            workload_oidc_issuer="https://iam.invalid/realms/baobab",
            idempiere_credentials_by_ad_client={100: _credentials(100, 3)},
        )
        handler = make_handler(config)
        self.assertIsInstance(handler._build_idempiere_client(None, 100, 3), RestIdempiereClient)


if __name__ == "__main__":
    import unittest
    unittest.main()
