"""The warehouse timezone input (ERP-CAP-08): ERP deployment configuration, declared per warehouse, never defaulted or derived.

Control Plane stores neither warehouse codes nor their timezones, so the input is ERP's. It must reach the plan without disturbing any
request accepted before it existed: that request's stored desired state has to reproduce the digest it was approved under."""
import json
import unittest
from dataclasses import replace

from provisioning.market_configuration import MarketConfigurationError, parse_deployment_configuration, parse_market_configuration
from provisioning.planner import build_plan, desired_state_digest, desired_state_json
from provisioning.request_state import request_from_state, verified_request

from test_provisioning_planner import valid_request


def market(**overrides):
    entry = {"currencies": ["UGX"], "localisation_profile": "ug-v1", "warehouse_codes": ["KLA", "JIN"],
             "warehouse_timezones": {"KLA": "Africa/Kampala", "JIN": "Africa/Kampala"}}
    entry.update(overrides)
    return {"markets": {"UG": entry}}


class ConfigurationTests(unittest.TestCase):
    def test_each_warehouse_has_exactly_one_declared_timezone(self):
        configured = parse_market_configuration(market())["UG"]
        self.assertEqual(configured.warehouse_timezones, (("JIN", "Africa/Kampala"), ("KLA", "Africa/Kampala")))

    def test_a_missing_extra_or_unnamed_timezone_is_a_configuration_error_not_a_default(self):
        for zones in ({"KLA": "Africa/Kampala"}, {"KLA": "Africa/Kampala", "JIN": "Africa/Kampala", "XXX": "Africa/Kampala"}, {}):
            with self.subTest(zones):
                with self.assertRaises(MarketConfigurationError):
                    parse_market_configuration(market(warehouse_timezones=zones))
        with self.assertRaises(MarketConfigurationError):
            parse_market_configuration({"markets": {"UG": {k: v for k, v in market()["markets"]["UG"].items()
                                                           if k != "warehouse_timezones"}}})

    def test_only_iana_region_city_names_are_accepted(self):
        for bad in ("UTC", "Kampala", "Africa Kampala", "", 3, None, "Africa/" + "x" * 80):
            with self.subTest(bad):
                with self.assertRaises(MarketConfigurationError):
                    parse_market_configuration(market(warehouse_timezones={"KLA": bad, "JIN": "Africa/Kampala"}))
        parse_market_configuration(market(warehouse_timezones={"KLA": "America/Argentina/Buenos_Aires", "JIN": "Etc/GMT+3"}))

    def test_a_placeholder_timezone_leaves_the_market_unconfigured(self):
        document = market(warehouse_timezones={"KLA": "REQUIRED_APPROVED_KLA_TZ", "JIN": "Africa/Kampala"})
        self.assertEqual(parse_market_configuration(document), {})

    def test_the_shipped_templates_parse_as_not_configured(self):
        import pathlib
        template = pathlib.Path(__file__).resolve().parents[2] / "config/provisioning/deployment.template.json"
        self.assertEqual(parse_deployment_configuration(json.loads(template.read_text())).markets, {})


class PlanTests(unittest.TestCase):
    def with_zones(self):
        request = valid_request()
        return replace(request, markets=(replace(request.markets[0], warehouse_timezones=(("KLA", "Africa/Kampala"),)),))

    def test_the_timezone_reaches_its_warehouse_step_and_changes_the_plan(self):
        zoned, plain = build_plan(self.with_zones()), build_plan(valid_request())
        [step] = [s for s in zoned.steps if s.kind.value == "create_warehouse"]
        self.assertEqual(step.payload["timezone"], "Africa/Kampala")
        self.assertNotEqual(zoned.desired_state_digest, plain.desired_state_digest)  # a different timezone is a different approved state

    def test_a_request_accepted_before_the_member_existed_keeps_its_serialisation_and_digest(self):
        plain = valid_request()
        self.assertNotIn("warehouse_timezones", desired_state_json(plain))
        [step] = [s for s in build_plan(plain).steps if s.kind.value == "create_warehouse"]
        self.assertNotIn("timezone", step.payload)
        stored = json.loads(desired_state_json(plain))  # what was stored when it was accepted
        self.assertEqual(desired_state_digest(request_from_state(stored)), desired_state_digest(plain))

    def test_a_zoned_request_round_trips_through_its_stored_state(self):
        request = self.with_zones()
        digest = desired_state_digest(request)
        restored = verified_request(json.loads(desired_state_json(request)), digest)
        self.assertEqual(restored.markets[0].warehouse_timezones, (("KLA", "Africa/Kampala"),))


if __name__ == "__main__":
    unittest.main()
