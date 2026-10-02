"""Every ERP-relevant example event in Shared parses as a canonical envelope, and the registry index in
modules/events/registry.py agrees with Shared's event registry and AsyncAPI.

Reads the Shared checkout named by SHARED_CONTRACTS_DIR and skips when it is not set. The exact-pin version
of this check (the commit declared in contracts.lock.yaml, enforced in CI) is ERP-COMPAT-06."""

import json
import os
import re
import unittest
from pathlib import Path

from events import registry
from events.cloudevent import CloudEvent, check_consumable

SHARED = os.environ.get("SHARED_CONTRACTS_DIR")


@unittest.skipUnless(SHARED, "SHARED_CONTRACTS_DIR not set")
class SharedEventExampleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(SHARED)
        self.examples = sorted((self.root / "contracts/erp/v1/examples").glob("*.json"))
        self.assertTrue(self.examples)

    def test_every_example_is_a_valid_envelope(self):
        for path in self.examples:
            with self.subTest(path.name):
                event = CloudEvent.from_wire(json.loads(path.read_text()))
                self.assertEqual(event.to_wire(), json.loads(path.read_text()))

    def test_example_types_sources_and_dataschemas_agree_with_the_registry_index(self):
        for path in self.examples:
            with self.subTest(path.name):
                event = CloudEvent.from_wire(json.loads(path.read_text()))
                self.assertEqual(event.dataschema, registry.dataschema_for(event.type))
                if event.type in registry.PRODUCED:
                    self.assertEqual(event.source, registry.ERP_SOURCE)
                else:
                    check_consumable(event)

    def test_registry_index_matches_shared_event_registry(self):
        text = (self.root / "contracts/events/v1/event-registry.yaml").read_text()
        entries = re.findall(r"- type: (\S+)\n\s+asyncapi: (\S+)\n(?:\s+producer: (\S+)\n)?", text)
        erp_produced = {t for t, _, producer in entries if producer == "baobab-erp"}
        self.assertEqual(erp_produced, set(registry.PRODUCED))
        for event_type, _, producer in entries:
            if event_type in registry.CONSUMED:
                self.assertEqual(producer, registry.CONSUMED[event_type][1])

    def test_dataschemas_resolve_to_real_shared_schemas(self):
        uris = list(registry.PRODUCED.values()) + [v[0] for v in registry.CONSUMED.values()]
        for uri in uris:
            with self.subTest(uri):
                path, _, fragment = uri.removeprefix(registry.CONTRACT_HOST).partition("#")
                document = json.loads((self.root / "contracts" / path).read_text())
                self.assertEqual(document["$id"], registry.CONTRACT_HOST + path)
                node = document
                for part in [p for p in fragment.split("/") if p]:
                    node = node[part]  # the fragment must name a real $defs entry
                self.assertIsInstance(node, dict)


if __name__ == "__main__":
    unittest.main()
