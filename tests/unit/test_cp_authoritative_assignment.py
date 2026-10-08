import copy
import unittest
from datetime import date, datetime, timedelta, timezone

from provisioning.authoritative_service import AuthoritativeProvisioningRequestFactory
from provisioning.cp_contract import AssignmentError, ErpMarketConfiguration, assignment_from_payload
from provisioning.finance_baseline import FinancialConfigurationBaseline
from provisioning.legal_entity_policy import (
    ConfiguredNativePlacementPolicy,
    NativeClientMode,
    NativePlacement,
    native_boundary,
)

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + "b2" * 32


def payload(entity="ZURIBEANS-ZA", market="ZA", **overrides) -> dict:
    """A Shared erp-assignment.schema.json ErpAssignment body."""
    body = {
        "tenant_id": "tn_01k4zuribeans",
        "tenant_provisioning_id": "tp_0199a1b2c3d47e8f9a0b1c2d3e4f5a6b",
        "plan_id": "plan_0199a1b2c3d47e8f", "plan_version": 3, "plan_digest": DIGEST,
        "legal_entity": {
            "legal_entity_id": entity, "legal_name": f"{entity} (Pty) Ltd", "jurisdiction_code": market,
            "registration_identifiers": [{"type": "COMPANY_REGISTRATION", "value": f"REG-{entity}", "verified": True}],
            "verification_state": "VERIFIED",
        },
        "markets": [{"market": market, "activities": ["SELLING", "IMPORTING"]}],
        "engine_id": "baobab-erp", "engine_instance_id": "ei_0199a1b2c3d47e8f",
        "isolation_requirement": "row_level_security",
        "capabilities": ["finance.order-consequence.process"],
        "issued_at": "2026-10-02T09:00:00Z", "expires_at": "2026-10-02T09:15:00Z",
    }
    body.update(overrides)
    return body


def baseline(entity="ZURIBEANS-ZA", **overrides) -> FinancialConfigurationBaseline:
    values = dict(
        legal_entity_id=entity, version=2, functional_currency="ZAR", fiscal_year_start_month=1,
        chart_of_accounts_template="coa-zb-v1", accounting_schema="ZB Primary", tax_profile="tax-za-v1",
        costing_method="average-po", effective_from=date(2026, 10, 1), approved_by="Thandi Nkosi",
        approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc), evidence_reference="FIN-CHG-2026-114")
    values.update(overrides)
    return FinancialConfigurationBaseline(**values)


class FakeFinance:
    """Resolves the baseline in force like the store does: latest effective_from not after the date."""
    def __init__(self, *baselines):
        self.baselines = baselines

    def effective(self, legal_entity_id, on):
        eligible = [b for b in self.baselines if b.legal_entity_id == legal_entity_id and b.effective_from <= on]
        return max(eligible, key=lambda b: (b.effective_from, b.version), default=None)


MARKETS = {"ZA": ErpMarketConfiguration(("ZAR", "USD"), "za-v1", ("JNB",), (("JNB", "Africa/Johannesburg"),)),
           "UG": ErpMarketConfiguration(("UGX", "USD"), "ug-v1", ("KLA",), (("KLA", "Africa/Kampala"),))}


def placement(mode=NativeClientMode.DEDICATED_CLIENT) -> ConfiguredNativePlacementPolicy:
    return ConfiguredNativePlacementPolicy({
        "ZURIBEANS-ZA": NativePlacement("Zuribeans_ZA", mode), "ZURIBEANS-UG": NativePlacement("Zuribeans_UG", mode)})


class FakeControlPlane:
    def __init__(self, body: dict):
        self._body = body

    def resolve_erp_assignment(self, *, tenant_id, tenant_provisioning_id, legal_entity_id):
        return assignment_from_payload(self._body)


def factory(body, mode=NativeClientMode.DEDICATED_CLIENT, markets=MARKETS, finance=None):
    return AuthoritativeProvisioningRequestFactory(
        control_plane=FakeControlPlane(body), native_placement=placement(mode), market_configuration=markets,
        finance=finance or FakeFinance(baseline(), baseline("ZURIBEANS-UG", functional_currency="UGX")),
        target_environment="production")


def build(body, on=date(2026, 10, 2), **kw):
    return factory(body, **kw).build(
        tenant_id=body["tenant_id"], tenant_provisioning_id=body["tenant_provisioning_id"],
        legal_entity_id=body["legal_entity"]["legal_entity_id"], on=on, now=NOW)


class AssignmentParsingTests(unittest.TestCase):
    def test_a_shared_erp_assignment_parses(self):
        a = assignment_from_payload(payload())
        self.assertEqual(a.legal_entity_id, "ZURIBEANS-ZA")
        self.assertEqual(a.capabilities, frozenset({"finance.order-consequence.process"}))
        self.assertEqual(a.isolation_requirement, "row_level_security")
        self.assertEqual(a.expires_at, datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc))

    def test_control_plane_registry_identifiers_and_erp_owned_decisions_are_refused_by_name(self):
        for field in ("capability_binding_id", "capability_bindings", "isolation_profile_id", "native_client_mode",
                      "native_client_key", "legal_entity_code", "target_environment", "currencies",
                      "localisation_profile", "warehouse_codes", "warehouse_timezones"):
            with self.subTest(field):
                with self.assertRaisesRegex(AssignmentError, field):
                    assignment_from_payload({**payload(), field: "x"})
                with self.assertRaisesRegex(AssignmentError, field):
                    body = payload()
                    body["legal_entity"] = {**body["legal_entity"], field: "x"}
                    assignment_from_payload(body)

    def test_an_unknown_member_is_refused(self):
        with self.assertRaisesRegex(AssignmentError, "unknown members: surprise"):
            assignment_from_payload({**payload(), "surprise": 1})

    def test_every_required_member_is_required(self):
        for field in ("tenant_id", "tenant_provisioning_id", "plan_id", "plan_version", "plan_digest", "legal_entity", "markets", "engine_id",
                      "engine_instance_id", "isolation_requirement", "capabilities", "issued_at", "expires_at"):
            with self.subTest(field):
                body = payload()
                del body[field]
                with self.assertRaises(AssignmentError):
                    assignment_from_payload(body)

    def test_duplicate_capabilities_are_refused(self):
        with self.assertRaisesRegex(AssignmentError, "unique"):
            assignment_from_payload(payload(capabilities=["a.b.c", "a.b.c"]))

    def test_an_instant_without_a_time_zone_is_refused(self):
        with self.assertRaisesRegex(AssignmentError, "time zone"):
            assignment_from_payload(payload(expires_at="2026-10-02T09:15:00"))


class AssignmentValidationTests(unittest.TestCase):
    def check(self, mutate, now=NOW, message=None):
        body = copy.deepcopy(payload())
        mutate(body)
        with self.assertRaisesRegex(AssignmentError, message or ""):
            assignment_from_payload(body).validate(now)

    def test_an_expired_assignment_authorises_nothing(self):
        self.check(lambda b: None, now=NOW + timedelta(minutes=15), message="expired")

    def test_an_unverified_legal_entity_fails_closed(self):
        self.check(lambda b: b["legal_entity"].update(verification_state="PENDING_REVIEW"), message="VERIFIED")

    def test_another_engine_fails_closed(self):
        self.check(lambda b: b.update(engine_id="baobab-trade"), message="baobab-trade")

    def test_duplicate_markets_fail_closed(self):
        self.check(lambda b: b["markets"].append(dict(b["markets"][0])), message="duplicate market")

    def test_no_markets_fail_closed(self):
        self.check(lambda b: b.update(markets=[]), message="market")

    def test_a_blank_required_value_fails_closed(self):
        self.check(lambda b: b.update(engine_instance_id=" "), message="engine_instance_id")

    def test_the_company_registration_must_be_unambiguous(self):
        for identifiers in ([], [{"type": "TAX_IDENTIFIER", "value": "T-1"}],
                            [{"type": "COMPANY_REGISTRATION", "value": "A"}, {"type": "COMPANY_REGISTRATION", "value": "B"}]):
            with self.subTest(identifiers):
                body = payload()
                body["legal_entity"]["registration_identifiers"] = identifiers
                with self.assertRaisesRegex(AssignmentError, "COMPANY_REGISTRATION"):
                    assignment_from_payload(body).registration_identifier()


class NativePlacementTests(unittest.TestCase):
    def test_native_boundary_comes_from_the_erp_policy_keyed_by_legal_entity_id(self):
        boundary = native_boundary(assignment_from_payload(payload()), placement(), NOW)
        self.assertEqual(boundary.native_client_key, "Zuribeans_ZA")
        self.assertEqual(boundary.mode, NativeClientMode.DEDICATED_CLIENT)

    def test_za_and_ug_are_distinct_legal_entities_and_native_boundaries(self):
        za = native_boundary(assignment_from_payload(payload()), placement(), NOW)
        ug = native_boundary(assignment_from_payload(payload("ZURIBEANS-UG", "UG")), placement(), NOW)
        self.assertNotEqual(za.native_client_key, ug.native_client_key)

    def test_an_unconfigured_legal_entity_fails_closed_without_inference(self):
        with self.assertRaisesRegex(AssignmentError, "no ERP native placement"):
            native_boundary(assignment_from_payload(payload("ZURIBEANS-KE", "KE")), placement(), NOW)

    def test_an_empty_native_client_key_fails_closed(self):
        policy = ConfiguredNativePlacementPolicy({"ZURIBEANS-ZA": NativePlacement(" ")})
        with self.assertRaisesRegex(AssignmentError, "empty"):
            native_boundary(assignment_from_payload(payload()), policy, NOW)


class AuthoritativeProvisioningRequestFactoryTests(unittest.TestCase):
    def test_build_materialises_a_request_from_the_cp_assignment_and_erp_owned_inputs(self):
        request = build(payload())
        self.assertEqual(request.provisioning_id, "tp_0199a1b2c3d47e8f9a0b1c2d3e4f5a6b.ZURIBEANS-ZA.v3")
        self.assertEqual(request.legal_entity_id, "ZURIBEANS-ZA")
        self.assertEqual(request.registration_identifier, "REG-ZURIBEANS-ZA")
        self.assertEqual(request.plan_digest, DIGEST)
        self.assertEqual(request.isolation_requirement, "row_level_security")
        self.assertEqual(request.requested_capabilities, frozenset({"finance.order-consequence.process"}))
        self.assertEqual(request.target_environment, "production")
        # The effective date and the accounting configuration are the Finance baseline's, with its approver.
        self.assertEqual(request.effective_date, date(2026, 10, 1))
        self.assertEqual((request.accounting.approved_by, request.accounting.functional_currency), ("Thandi Nkosi", "ZAR"))
        # Per-market configuration is ERP's; the activities are CP's, in ERP's lower-case vocabulary.
        market = request.markets[0]
        self.assertEqual((market.market_id, market.country_code), ("ZA", "ZA"))
        self.assertEqual(market.participation_capabilities, frozenset({"selling", "importing"}))
        self.assertEqual((market.currencies, market.localisation_profile, market.warehouse_codes), (("ZAR", "USD"), "za-v1", ("JNB",)))

    def test_plan_version_must_be_a_positive_integer(self):
        for bad in (0, -1, True):
            with self.subTest(bad):
                with self.assertRaisesRegex(AssignmentError, "plan_version"):
                    assignment_from_payload(payload(plan_version=bad)).validate(NOW)

    def test_the_idempotency_key_is_erp_derived_stable_and_bound_to_the_approved_plan(self):
        first, again = build(payload()), build(payload())
        self.assertEqual(first.idempotency_key, again.idempotency_key)
        self.assertTrue(first.idempotency_key.startswith("erp-prov-"))
        self.assertNotEqual(first.idempotency_key, build(payload(plan_digest="sha256:" + "c3" * 32)).idempotency_key)
        # A replan is a new approved plan, so it is a new provisioning, not a rewrite of the old one.
        self.assertNotEqual(first.idempotency_key, build(payload(plan_version=4)).idempotency_key)
        self.assertNotEqual(first.provisioning_id, build(payload(plan_version=4)).provisioning_id)
        self.assertNotEqual(first.provisioning_id, build(payload("ZURIBEANS-UG", "UG")).provisioning_id)
        self.assertNotEqual(first.idempotency_key, build(payload("ZURIBEANS-UG", "UG")).idempotency_key)

    def test_a_cross_boundary_assignment_is_refused_whatever_it_validates_as(self):
        body = payload("ZURIBEANS-UG", "UG")
        for ask in ({"tenant_id": "tn_01k4other"}, {"tenant_provisioning_id": "tp_ffffffffffffffffffffffffffffffff"},
                    {"legal_entity_id": "ZURIBEANS-ZA"}):
            with self.subTest(ask):
                asked = {"tenant_id": body["tenant_id"], "tenant_provisioning_id": body["tenant_provisioning_id"],
                         "legal_entity_id": "ZURIBEANS-UG", **ask}
                with self.assertRaisesRegex(AssignmentError, "cross-boundary"):
                    factory(body).build(on=date(2026, 10, 2), now=NOW, **asked)

    def test_a_market_without_erp_configuration_cannot_be_provisioned(self):
        with self.assertRaisesRegex(AssignmentError, "no ERP market configuration for 'KE'"):
            build(payload("ZURIBEANS-ZA", "ZA", markets=[{"market": "KE", "activities": ["SELLING"]}]))

    def test_existing_client_mode_the_adapter_cannot_honour_fails_closed(self):
        with self.assertRaises(NotImplementedError):
            build(payload(), mode=NativeClientMode.EXISTING_CLIENT)

    def test_an_expired_assignment_is_not_provisioned_from(self):
        with self.assertRaisesRegex(AssignmentError, "expired"):
            factory(payload()).build(
                tenant_id="tn_01k4zuribeans", tenant_provisioning_id="tp_0199a1b2c3d47e8f9a0b1c2d3e4f5a6b",
                legal_entity_id="ZURIBEANS-ZA", on=date(2026, 10, 2), now=NOW + timedelta(hours=1))

    def test_without_a_finance_approved_baseline_in_force_nothing_is_provisioned(self):
        with self.assertRaisesRegex(AssignmentError, "no Finance-approved baseline"):
            build(payload(), finance=FakeFinance())
        # A baseline not yet in force is not in force.
        with self.assertRaisesRegex(AssignmentError, "no Finance-approved baseline"):
            build(payload(), on=date(2026, 9, 30))

    def test_another_legal_entitys_baseline_is_refused_even_if_the_source_returns_it(self):
        class Wrong:
            def effective(self, legal_entity_id, on):
                return baseline("ZURIBEANS-UG")
        with self.assertRaisesRegex(AssignmentError, "another legal entity"):
            build(payload(), finance=Wrong())

    def test_the_latest_version_in_force_wins(self):
        newer = baseline(version=3, tax_profile="tax-za-v2", effective_from=date(2026, 10, 2))
        request = build(payload(), finance=FakeFinance(baseline(), newer))
        self.assertEqual(request.accounting.tax_profile, "tax-za-v2")
        self.assertEqual(request.effective_date, date(2026, 10, 2))


if __name__ == "__main__":
    unittest.main()
