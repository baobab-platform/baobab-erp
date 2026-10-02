import unittest

import jsonschema

import _shared as shared
from events import registry

# Contracts the ERP implementation reads or depends on. Every one must be in contracts.lock.yaml so a Shared
# change to it is reported as drift and the pin cannot silently move under the code.
CODE_DEPENDS_ON = {
    "contracts/erp/v1/openapi.yaml",
    "contracts/erp/v1/asyncapi.yaml",
    "contracts/erp/v1/mapping.schema.json",
    "contracts/erp/v1/domain.schema.json",
    "contracts/erp/v1/system-of-record.yaml",
    "contracts/errors/v1/problem-details.schema.json",
    "contracts/events/v1/envelope.schema.json",
    "contracts/events/v1/event-registry.yaml",
    "contracts/events/v1/compatibility/legacy-trade-erp-event.json",
    "contracts/idempotency/v1/policy.yaml",
    "contracts/control-plane/v1/domain.schema.json",
    "contracts/control-plane/v1/access-token-claims.schema.json",
    "contracts/control-plane/v1/erp-assignment.schema.json",
    "contracts/control-plane/v1/examples/erp-assignment.json",
    "contracts/buyer-organisation/v1/asyncapi.yaml",
}


def _dataschema_files():
    uris = list(registry.PRODUCED.values()) + [v[0] for v in registry.CONSUMED.values()]
    return {"contracts/" + u.removeprefix(shared.HOST).partition("#")[0] for u in uris}


class PinTests(unittest.TestCase):
    def test_runs_against_exactly_the_commit_the_lock_pins(self):
        self.assertEqual(shared.LOCK["source"]["repository"], "baobab-platform/shared")
        self.assertEqual(shared.head(), shared.PIN)

    def test_every_locked_contract_exists_at_the_pin(self):
        for contract in shared.LOCK["contracts"]:
            with self.subTest(contract):
                self.assertTrue((shared.ROOT / contract).is_file())

    def test_every_shared_schema_loads_so_no_reference_can_dangle(self):
        self.assertEqual(shared.UNLOADED, [])

    def test_the_lock_names_every_contract_the_code_depends_on(self):
        locked = set(shared.LOCK["contracts"])
        required = CODE_DEPENDS_ON | _dataschema_files()
        self.assertEqual(sorted(required - locked), [])

    def test_the_lock_lists_nothing_twice(self):
        contracts = shared.LOCK["contracts"]
        self.assertEqual(len(contracts), len(set(contracts)))

    def test_format_checking_is_actually_active(self):
        for name in ("date-time", "uri", "uuid", "date"):
            self.assertIn(name, shared.FORMATS.checkers, f"format {name!r} is not enforced; install jsonschema[format-nongpl]")
        with self.assertRaises(jsonschema.ValidationError):
            shared.validate(shared.schema_uri("events/v1/envelope.schema.json"), {"time": "x"})


if __name__ == "__main__":
    unittest.main()
