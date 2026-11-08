"""Native UUID history/readback negatives; fixtures are never JVM evidence."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from inbox.execution_support import Stop, Target
from integration.idempiere_client import IdempiereClientError
from order_to_cash.inbox_execution import _execute, _find_or_create
from order_to_cash.native_reference import NativeOrderReference

MODULE = "order_to_cash.inbox_execution"


class ExecutionReferenceTests(unittest.TestCase):
    def known_attempt(self, version):
        order = SimpleNamespace(legal_entity_id="LE-TEST", commerce_order_id="order_full_fixture",
                                order_version=version)
        claim = SimpleNamespace(data={}, tenant_id="tn_fixture")
        db = Mock()
        manager = MagicMock()
        manager.__enter__.return_value.held = True
        return order, claim, db, manager

    def test_older_version_preserves_history_without_reserving_or_mutating(self):
        order, claim, db, lock = self.known_attempt(1)
        with patch(MODULE + ".parse_placed_order", return_value=order), \
             patch(MODULE + ".PostgresOrderMasterData") as masters, \
             patch(MODULE + ".AdvisoryLock", return_value=lock), \
             patch(MODULE + ".PostgresOrderConsequenceStore") as consequences, \
             patch(MODULE + ".references.reserve") as reserve:
            masters.return_value.target.return_value = Target(11, 11, "ei_fixture")
            consequences.return_value.get.return_value = SimpleNamespace(
                legal_entity_id="LE-TEST", order_version=2)
            provider = Mock()
            result = _execute(claim, db, Mock(), provider, Mock(), None)
            self.assertEqual(result.code, "STALE_VERSION")
            reserve.assert_not_called()
            provider.assert_not_called()

    def test_newer_version_stays_an_unsupported_amendment(self):
        order, claim, db, lock = self.known_attempt(3)
        with patch(MODULE + ".parse_placed_order", return_value=order), \
             patch(MODULE + ".PostgresOrderMasterData") as masters, \
             patch(MODULE + ".AdvisoryLock", return_value=lock), \
             patch(MODULE + ".PostgresOrderConsequenceStore") as consequences, \
             patch(MODULE + ".references.reserve") as reserve:
            masters.return_value.target.return_value = Target(11, 11, "ei_fixture")
            consequences.return_value.get.return_value = SimpleNamespace(
                legal_entity_id="LE-TEST", order_version=2)
            with self.assertRaises(Stop) as raised:
                _execute(claim, db, Mock(), Mock(), Mock(), None)
            self.assertEqual(raised.exception.outcome.code, "AMENDMENT_UNSUPPORTED")
            reserve.assert_not_called()

    def test_equal_version_changed_facts_cannot_replay_success(self):
        order, claim, db, lock = self.known_attempt(2)
        with patch(MODULE + ".parse_placed_order", return_value=order), \
             patch(MODULE + ".PostgresOrderMasterData") as masters, \
             patch(MODULE + ".AdvisoryLock", return_value=lock), \
             patch(MODULE + ".PostgresOrderConsequenceStore") as consequences, \
             patch(MODULE + ".references.configured", return_value=True), \
             patch(MODULE + ".references.reserve", side_effect=IdempiereClientError("changed")):
            masters.return_value.target.return_value = Target(11, 11, "ei_fixture")
            consequences.return_value.get.return_value = SimpleNamespace(
                legal_entity_id="LE-TEST", order_version=2)
            with self.assertRaises(Stop) as raised:
                _execute(claim, db, Mock(), Mock(), Mock(), None)
            self.assertEqual(raised.exception.outcome.code, "NATIVE_REFERENCE_CHANGED")

    def test_uuid_profile_refuses_a_provider_without_independent_business_readback(self):
        reference = self.reference()
        provider = SimpleNamespace(query=Mock(), create_record=Mock())
        with patch(MODULE + "._protected_finance_runtime", return_value=False), \
             self.assertRaises(Stop) as raised:
            _find_or_create(provider, SimpleNamespace(commerce_order_id=reference.commerce_order_id),
                            11, (), reference=reference)
        self.assertEqual(raised.exception.outcome.code, "ENGINE_UNAVAILABLE")
        provider.query.assert_not_called()
        provider.create_record.assert_not_called()

    @staticmethod
    def reference():
        return NativeOrderReference("tn_fixture", "LE-TEST", "order_full_fixture",
            "ei_fixture", 11, 11, "15be9a37-3545-4cdf-8f20-842b4c84f771", True)

    def test_initial_creation_requires_business_readback_before_reporting_success(self):
        # A provider-returned ID alone must never become an EXECUTED outcome.
        reference = self.reference()
        order = SimpleNamespace(commerce_order_id=reference.commerce_order_id, currency="USD")
        provider = SimpleNamespace(
            query=Mock(return_value=[]), create_record=Mock(return_value=42),
            assert_existing_order_matches=Mock(side_effect=IdempiereClientError("foreign facts")))
        with patch(MODULE + "._protected_finance_runtime", return_value=False), \
             patch(MODULE + "._verify_units"), \
             patch(MODULE + ".references.mark_creation_attempt") as attempted, \
             self.assertRaises(Stop) as raised:
            _find_or_create(provider, order, 11, (), reference=reference, connection=Mock())
        self.assertEqual(raised.exception.outcome.code, "ENGINE_UNAVAILABLE")
        attempted.assert_called_once()
        provider.create_record.assert_called_once()
        provider.assert_existing_order_matches.assert_called_once_with(
            42, order, 11, (), native_uuid=reference.native_uuid)
