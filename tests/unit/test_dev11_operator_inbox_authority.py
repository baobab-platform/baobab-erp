"""DEV-11: an accepted event must never invent a legal actor or native permit.

All fixtures are synthetic UNIT tests. These are NOT connected IAM/CP or real
iDempiere evidence; only the strict preflight/negative semantics are asserted.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from application.inbox_authority import (
    AuthorityEntry, NativeOrderProviderReadiness, OperatorAuthorityRegistry,
    from_operator_configuration, _ObservedCP, _ObservedDocumentary,
    _ObservedNativeProvider,
)
from inbox.postgres_queue import Claim
from order_to_cash.legal_actor_gate import LegalActorNotAuthorised, LegalActorOperation
from order_to_cash.legal_actor_http_client import LegalActorAssessmentUnavailable


ENTRY = {
    "event_id": "1d032305-669c-45df-b988-01166de4c14c",
    "source": "urn:baobab-platform:service:baobab-trade",
    "tenant_id": "tn_dev11synthetic",
    "idempotency_key": "dev11-rabbit-connected:1d032305-669c-45df-b988-01166de4c14c",
    "commerce_order_id": "order_dev11_fixture",
    "legal_entity_id": "LE-DEV11-SYNTHETIC",
    "context_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6b",
    "operating_organisation_id": "0199a1b2-c3d4-7e8f-9a0b-1c2d3e4f5a6c",
    "market": "ZA",
    "activity": "B2B_TRADE_ORDER",
    "capability": "accounting.order.create",
    "authority_reference": "approved:dev11/cp/order/v1",
    "engine_instance_id": "ei_dev11synthetic",
    "ad_client_id": 11,
    "ad_org_id": 11,
    "finance_baseline_version": 1,
}


def claim():
    return Claim(
        row_id=1, event_id=ENTRY["event_id"],
        event_type="com.baobab-platform.trade.order.placed.v1",
        tenant_id=ENTRY["tenant_id"], data={
            "commerce_order_id": ENTRY["commerce_order_id"],
            "legal_entity_id": ENTRY["legal_entity_id"],
        }, attempts=1, received_at=datetime.now(UTC),
        correlation_id="ea733cd4-0daa-4c52-89f8-a940cfa8a1ac",
        worker_id="synthetic-dev11", source=ENTRY["source"],
        idempotency_key=ENTRY["idempotency_key"],
    )


class Cursor:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchone(self):
        if "baobab_native.native_placement" in self.sql:
            return (self.state["placement"],)
        if "baobab.tenant_mapping" in self.sql:
            return (self.state["target"],)
        if "baobab.financial_configuration_baseline b" in self.sql:
            return (self.state["baseline"],)
        raise AssertionError("unexpected native provider query")


class Connection:
    def __init__(self, **changes):
        self.state = {"placement": 1, "target": 1, "baseline": 1, **changes}

    def cursor(self):
        return Cursor(self.state)


class Engine:
    def __init__(self):
        self.reads = []

    def get_record(self, table, record_id):
        self.reads.append((table, record_id))
        if table == "AD_Org":
            return {"id": 11, "AD_Client_ID": {"id": 11}, "IsActive": "Y"}
        if table == "AD_Client":
            return {"id": 11, "IsActive": "Y"}
        raise AssertionError("unexpected iDempiere REST read")


def operation():
    return LegalActorOperation(
        context_id=ENTRY["context_id"], tenant_id=ENTRY["tenant_id"],
        operating_organisation_id=ENTRY["operating_organisation_id"],
        expected_legal_entity_id=ENTRY["legal_entity_id"],
        role="CONTRACTING_PARTY", activity=ENTRY["activity"],
        market=ENTRY["market"], capability=ENTRY["capability"],
        operation_reference=ENTRY["commerce_order_id"],
    )


class OperatorAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "approved.json"
        self.write({"schema": "baobab.erp.dev11.operator-authority.v1",
                    "entries": [ENTRY]})

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")
        self.path.chmod(0o600)

    def load(self):
        return OperatorAuthorityRegistry(str(self.path))

    def test_one_operator_bound_event_matches_only_exact_source_identity_and_order(self):
        registry = self.load()
        self.assertEqual(registry.for_claim(claim()), AuthorityEntry.parse(ENTRY))
        self.assertIsNone(registry.for_claim(replace(claim(), source="urn:bad:trade")))
        self.assertIsNone(registry.for_claim(replace(claim(), tenant_id="tn_foreign")))
        self.assertIsNone(registry.for_claim(replace(claim(), idempotency_key="different")))
        self.assertIsNone(registry.for_claim(replace(claim(), data={
            "commerce_order_id": "order_different",
            "legal_entity_id": ENTRY["legal_entity_id"],
        })))
        self.assertIsNone(registry.for_claim(replace(
            claim(), event_type="com.baobab-platform.trade.customer.projected.v1")))
        self.assertIsNone(registry.for_claim(replace(
            claim(), event_id="00000000-0000-4000-8000-000000000123")))

    def test_registry_cannot_create_a_second_grant_for_same_event(self):
        self.write({"schema": "baobab.erp.dev11.operator-authority.v1",
                    "entries": [ENTRY, ENTRY]})
        with self.assertRaisesRegex(ValueError, "DEV11_DUPLICATE_EVENT_AUTHORITY"):
            self.load()

    def test_extra_fields_cannot_override_tenant_or_principal(self):
        self.write({"schema": "baobab.erp.dev11.operator-authority.v1",
                    "entries": [{**ENTRY, "mandate_authorised": True}]})
        with self.assertRaisesRegex(ValueError, "DEV11_REGISTRY_ENTRY_FIELDS_INVALID"):
            self.load()

    def test_duplicate_json_fields_are_denied(self):
        self.path.write_text(
            '{"schema":"baobab.erp.dev11.operator-authority.v1","entries":[],'
            '"entries":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "DEV11_REGISTRY_DUPLICATE_PROPERTY"):
            self.load()

    def test_group_writable_operator_file_is_denied(self):
        self.path.chmod(0o664)
        with self.assertRaisesRegex(ValueError, "DEV11_OPERATOR_FILE_NOT_IMMUTABLE"):
            self.load()

    def test_native_provider_verifies_real_placement_baseline_and_client_org(self):
        engine = Engine()
        provider = NativeOrderProviderReadiness(
            Connection(), lambda client, org: engine, AuthorityEntry.parse(ENTRY))
        provider.ensure_legal_actor_usable(operation(), "mandate-dev11-test")
        self.assertEqual(engine.reads, [("AD_Org", 11), ("AD_Client", 11)])

    def test_missing_native_placement_blocks_before_engine_call(self):
        engine = Engine()
        provider = NativeOrderProviderReadiness(
            Connection(placement=0), lambda client, org: engine, AuthorityEntry.parse(ENTRY))
        with self.assertRaises(LegalActorNotAuthorised):
            provider.ensure_legal_actor_usable(operation(), "mandate-dev11-test")
        self.assertFalse(engine.reads)

    def test_withdrawn_or_stale_finance_baseline_blocks(self):
        provider = NativeOrderProviderReadiness(
            Connection(baseline=0), lambda *_: Engine(), AuthorityEntry.parse(ENTRY))
        with self.assertRaises(LegalActorNotAuthorised):
            provider.ensure_legal_actor_usable(operation(), "mandate-dev11-test")

    def test_broken_native_postgres_migration_denies_and_rolls_back(self):
        import psycopg

        class MissingNativePlacement:
            rolled_back = False

            def cursor(self):
                raise psycopg.OperationalError("native migration absent")

            def rollback(self):
                self.rolled_back = True

        database = MissingNativePlacement()
        engine = Engine()
        provider = NativeOrderProviderReadiness(
            database, lambda *_: engine, AuthorityEntry.parse(ENTRY))
        with self.assertRaisesRegex(
                LegalActorNotAuthorised, "ERP native placement or Finance baseline unavailable"):
            provider.ensure_legal_actor_usable(operation(), "mandate-synthetic")
        self.assertTrue(database.rolled_back)
        self.assertFalse(engine.reads)

    def test_empty_mandate_cannot_create_native_permit(self):
        provider = NativeOrderProviderReadiness(
            Connection(), lambda *_: Engine(), AuthorityEntry.parse(ENTRY))
        with self.assertRaises(LegalActorNotAuthorised):
            provider.ensure_legal_actor_usable(operation(), "")

    def test_operator_file_cannot_activate_protected_staging_or_production(self):
        for environment in ("staging", "production"):
            with self.subTest(environment=environment), patch.dict(
                    os.environ, {"BAOBAB_ERP_INBOX_AUTHORITY_REGISTRY_FILE": str(self.path),
                                 "BAOBAB_ENVIRONMENT": environment}):
                with self.assertRaisesRegex(RuntimeError, "DEV11_OPERATOR_REGISTRY_NOT_PRODUCTION_AUTHORITY"):
                    from_operator_configuration(None, None)

    def test_private_cp_failure_stage_preserves_veto_without_sensitive_text(self):
        private = "bearer-not-for-public-output"
        original = LegalActorAssessmentUnavailable(private, stage="CP_RESPONSE_CONTRACT")
        class CP:
            def assess(self, _):
                raise original
        for environment in ("integration", "staging", "production"):
            out = StringIO()
            with patch.dict(os.environ, {
                "BAOBAB_ENVIRONMENT": environment,
                "DEV11_REAL_NATIVE_ACCEPTANCE": "true",
                "BAOBAB_DEV11_REAL_JVM_GATE_ENABLED": "true",
            }), redirect_stdout(out), self.assertRaises(LegalActorAssessmentUnavailable) as refused:
                _ObservedCP(CP()).assess({})
            self.assertIs(refused.exception, original)
            self.assertNotIn(private, out.getvalue())
            if environment == "integration":
                self.assertIn("CP_RESPONSE_CONTRACT", out.getvalue())
            else:
                self.assertEqual(out.getvalue(), "")

    def test_integration_stage_observers_do_not_modify_replies_or_native_veto(self):
        private = "super-secret-bearer-must-not-be-printed"
        class CP:
            def assess(self, request):
                return {"status": "DENIED", "private_bearer": private}
        class Documentary:
            def assess(self, request):
                return {"blocked": True, "private_bearer": private}
        class Provider:
            def ensure_legal_actor_usable(self, operation, mandate_id):
                raise LegalActorNotAuthorised("native provider denied")
        buf = StringIO()
        with patch.dict(os.environ, {
            "BAOBAB_ENVIRONMENT": "integration",
            "DEV11_REAL_NATIVE_ACCEPTANCE": "true",
            "BAOBAB_DEV11_REAL_JVM_GATE_ENABLED": "true",
        }), redirect_stdout(buf):
            self.assertEqual(_ObservedCP(CP()).assess({}), {
                "status": "DENIED", "private_bearer": private})
            self.assertEqual(_ObservedDocumentary(Documentary()).assess({}), {
                "blocked": True, "private_bearer": private})
            with self.assertRaises(LegalActorNotAuthorised):
                _ObservedNativeProvider(Provider()).ensure_legal_actor_usable(
                    operation(), "synthetic-mandate")
        text = buf.getvalue()
        self.assertIn("DEV11_NATIVE_AUTHORITY_STAGE CP_RESPONSE_RECEIVED", text)
        self.assertIn("DEV11_NATIVE_AUTHORITY_STAGE DOCUMENTARY_RESPONSE_RECEIVED", text)
        self.assertIn("DEV11_NATIVE_AUTHORITY_STAGE NATIVE_PROVIDER_START", text)
        self.assertNotIn("NATIVE_PROVIDER_READY", text)
        self.assertNotIn(private, text)
        self.assertNotIn("blocked", text)
        with patch.dict(os.environ, {
            "BAOBAB_ENVIRONMENT": "production",
            "DEV11_REAL_NATIVE_ACCEPTANCE": "true",
            "BAOBAB_DEV11_REAL_JVM_GATE_ENABLED": "true",
        }), redirect_stdout(buf := StringIO()):
            _ObservedCP(CP()).assess({})
        self.assertEqual(buf.getvalue(), "")

    def test_unsafe_oauth_origin_is_denied_before_token_request(self):
        secret = Path(self.tempdir.name) / "workload-secret"
        secret.write_text("dev11-synthetic-issuer-secret-long", encoding="utf-8")
        secret.chmod(0o600)
        settings = {
            "BAOBAB_ERP_INBOX_AUTHORITY_REGISTRY_FILE": str(self.path),
            "BAOBAB_ENVIRONMENT": "development",
            "BAOBAB_ERP_CP_URL": "https://cp.example.invalid",
            "BAOBAB_ERP_CP_OAUTH_TOKEN_URL": "http://issuer.example.invalid/oauth2/token",
            "BAOBAB_ERP_CP_WORKLOAD_CLIENT_ID": "erp-dev11-worker",
            "BAOBAB_ERP_CP_WORKLOAD_SECRET_FILE": str(secret),
        }
        with patch.dict(os.environ, settings):
            with self.assertRaisesRegex(RuntimeError, "DEV11_OPERATOR_OAUTH_TOKEN_URL_NOT_SECURE"):
                from_operator_configuration(None, None)


if __name__ == "__main__":
    unittest.main()
