import unittest
from datetime import date, datetime, timedelta, timezone

from provisioning.authoritative_service import AuthoritativeProvisioningRequestFactory
from provisioning.cp_contract import (
    AssignmentError,
    CpErpAssignment,
    CpMarketAssignment,
    FinanceBaseline,
    NativeClientMode,
    assignment_from_payload,
)
from provisioning.legal_entity_policy import native_boundary


def assignment(code: str, entity: str, market: str, country: str, mode: NativeClientMode = NativeClientMode.DEDICATED_CLIENT) -> CpErpAssignment:
    now = datetime.now(timezone.utc)
    return CpErpAssignment(
        assignment_version="v1", provisioning_id=f"prov-{code}",
        idempotency_key=f"idem-{code}", tenant_id="tenant-zuribeans",
        legal_entity_id=entity, legal_entity_code=code, legal_name=code,
        registration_identifier=f"REG-{code}", jurisdiction_code=country,
        engine_instance_id="erp-af-01", isolation_profile_id="iso-zb",
        capability_binding_id=f"binding-{code}", target_environment="production",
        effective_date=date(2026, 9, 1), native_client_mode=mode,
        native_client_key=code,
        markets=(CpMarketAssignment(market, country, frozenset({"selling", "procurement"}), ("ZAR",) if country == "ZA" else ("UGX",), f"{country.lower()}-v1"),),
        requested_capabilities=frozenset({"erp.accounting", "erp.accounts-payable", "erp.accounts-receivable", "erp.inventory", "erp.procurement"}),
        issued_at=now, expires_at=now + timedelta(hours=1),
    )


def finance_baseline() -> FinanceBaseline:
    return FinanceBaseline(
        functional_currency="ZAR", fiscal_year_start_month=1,
        chart_of_accounts_template="coa-zb-v1", accounting_schema="ZB Primary",
        tax_profile="tax-za-v1", costing_method="average-po",
        approved_by="finance-user", approved_at=datetime.now(timezone.utc),
    )


class FakeControlPlane:
    def __init__(self, assignment_to_return: CpErpAssignment):
        self._assignment = assignment_to_return

    def resolve_erp_assignment(self, *, tenant_id, legal_entity_id, capability_key):
        return self._assignment


class CpErpAssignmentTests(unittest.TestCase):
    def test_za_and_ug_are_distinct_legal_entities_and_native_boundaries(self):
        za = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        ug = assignment("Zuribeans_UG", "le-zb-ug", "market-ug", "UG")
        za.validate()
        ug.validate()
        self.assertNotEqual(za.legal_entity_id, ug.legal_entity_id)
        self.assertNotEqual(za.native_client_key, ug.native_client_key)

    def test_expired_assignment_fails_closed(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        object.__setattr__(a, "expires_at", datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.assertRaises(AssignmentError):
            a.validate()

    def test_non_production_environment_fails_closed(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        object.__setattr__(a, "target_environment", "staging")
        with self.assertRaises(AssignmentError):
            a.validate()

    def test_duplicate_market_id_fails_closed(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        object.__setattr__(a, "markets", (a.markets[0], a.markets[0]))
        with self.assertRaises(AssignmentError):
            a.validate()

    def test_missing_required_field_fails_closed(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        object.__setattr__(a, "engine_instance_id", "")
        with self.assertRaises(AssignmentError):
            a.validate()

    def test_assignment_from_payload_round_trips(self):
        payload = {
            "assignment_version": "v1", "provisioning_id": "prov-za", "idempotency_key": "idem-za",
            "tenant_id": "tenant-zuribeans", "legal_entity_id": "le-zb-za", "legal_entity_code": "Zuribeans_ZA",
            "legal_name": "Zuribeans_ZA", "registration_identifier": "REG-ZA", "jurisdiction_code": "ZA",
            "engine_instance_id": "erp-af-01", "isolation_profile_id": "iso-zb", "capability_binding_id": "binding-za",
            "target_environment": "production", "effective_date": "2026-09-01",
            "native_client_mode": "dedicated_client", "native_client_key": "Zuribeans_ZA",
            "markets": [{"market_id": "market-za", "country_code": "ZA", "capabilities": ["selling"], "currencies": ["ZAR"], "localisation_profile": "za-v1"}],
            "requested_capabilities": ["erp.accounting"],
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
        result = assignment_from_payload(payload)
        self.assertEqual(result.legal_entity_id, "le-zb-za")
        self.assertEqual(result.native_client_mode, NativeClientMode.DEDICATED_CLIENT)


class NativeBoundaryTests(unittest.TestCase):
    def test_native_boundary_does_not_infer_anything_beyond_the_assignment(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        boundary = native_boundary(a)
        self.assertEqual(boundary.legal_entity_id, a.legal_entity_id)
        self.assertEqual(boundary.native_client_key, a.native_client_key)
        self.assertEqual(boundary.mode, NativeClientMode.DEDICATED_CLIENT)


class AuthoritativeProvisioningRequestFactoryTests(unittest.TestCase):
    def test_build_materializes_a_request_from_the_cp_assignment(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
        factory = AuthoritativeProvisioningRequestFactory(control_plane=FakeControlPlane(a))

        request = factory.build(tenant_id="tenant-zuribeans", legal_entity_id="le-zb-za", finance=finance_baseline())

        self.assertEqual(request.provisioning_id, a.provisioning_id)
        self.assertEqual(request.legal_entity_id, "le-zb-za")
        self.assertEqual(len(request.markets), 1)

    def test_build_rejects_a_cross_boundary_assignment(self):
        a = assignment("Zuribeans_UG", "le-zb-ug", "market-ug", "UG")
        factory = AuthoritativeProvisioningRequestFactory(control_plane=FakeControlPlane(a))

        with self.assertRaises(ValueError):
            factory.build(tenant_id="tenant-zuribeans", legal_entity_id="le-zb-za", finance=finance_baseline())

    def test_build_rejects_existing_client_mode_the_adapter_cannot_honour(self):
        a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA", mode=NativeClientMode.EXISTING_CLIENT)
        factory = AuthoritativeProvisioningRequestFactory(control_plane=FakeControlPlane(a))

        with self.assertRaises(NotImplementedError):
            factory.build(tenant_id="tenant-zuribeans", legal_entity_id="le-zb-za", finance=finance_baseline())


if __name__ == "__main__":
    unittest.main()
