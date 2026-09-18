import unittest

from provisioning.master_data import CanonicalMasterRecord, MasterDataKind
from provisioning.master_data_adapter import IdempiereMasterDataBootstrapper


class FakeClient:
    def __init__(self):
        self.records = {}
        self.next = 10

    def create_record(self, table, fields):
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        return self.next

    def get_record(self, table, record_id):
        return self.records[(table, record_id)]

    def update_record(self, table, record_id, fields):
        self.records[(table, record_id)].update(fields)


class FakeMappings:
    def __init__(self):
        self.values = {}

    def get(self, *, engine_instance_id, legal_entity_id, kind, canonical_id):
        return self.values.get((engine_instance_id, legal_entity_id, kind, canonical_id))

    def put(self, *, engine_instance_id, legal_entity_id, kind, canonical_id, native_id, desired_digest, source_version):
        self.values[(engine_instance_id, legal_entity_id, kind, canonical_id)] = (
            native_id, desired_digest, source_version,
        )


def coffee_record(**overrides) -> CanonicalMasterRecord:
    defaults = dict(
        kind=MasterDataKind.PRODUCT, canonical_id="prod-1", external_key="COFFEE-1",
        legal_entity_id="le-za", payload={"Name": "Coffee"}, contract_version="v1", source_version="1",
    )
    defaults.update(overrides)
    return CanonicalMasterRecord(**defaults)


class MasterDataBootstrapTests(unittest.TestCase):
    def test_idempotent_product_bootstrap(self):
        client, mappings = FakeClient(), FakeMappings()
        bootstrapper = IdempiereMasterDataBootstrapper(client=client, mappings=mappings)
        record = coffee_record()

        first = bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[record])
        second = bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[record])

        self.assertEqual(first.created, 1)
        self.assertEqual(second.reused, 1)
        self.assertEqual(len(client.records), 1)

    def test_cross_legal_entity_fails_closed(self):
        client, mappings = FakeClient(), FakeMappings()
        bootstrapper = IdempiereMasterDataBootstrapper(client=client, mappings=mappings)
        record = coffee_record(legal_entity_id="le-ug")

        with self.assertRaises(ValueError):
            bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[record])

    def test_product_accounting_is_reported_as_drift_not_applied(self):
        client, mappings = FakeClient(), FakeMappings()
        bootstrapper = IdempiereMasterDataBootstrapper(client=client, mappings=mappings)
        record = coffee_record(kind=MasterDataKind.PRODUCT_ACCOUNTING, canonical_id="prod-1-accounting")

        result = bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[record])

        self.assertEqual(result.created, 0)
        self.assertEqual(len(result.drift), 1)
        self.assertEqual(len(client.records), 0)

    def test_newer_source_version_updates_the_native_record(self):
        client, mappings = FakeClient(), FakeMappings()
        bootstrapper = IdempiereMasterDataBootstrapper(client=client, mappings=mappings)
        bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[coffee_record()])

        updated = coffee_record(payload={"Name": "Arabica Coffee"}, source_version="2")
        result = bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[updated])

        self.assertEqual(result.updated, 1)
        self.assertEqual(len(result.drift), 0)

    def test_stale_source_version_is_reported_as_drift_not_applied(self):
        client, mappings = FakeClient(), FakeMappings()
        bootstrapper = IdempiereMasterDataBootstrapper(client=client, mappings=mappings)
        bootstrapper.bootstrap(
            engine_instance_id="erp", legal_entity_id="le-za",
            records=[coffee_record(source_version="5")],
        )

        stale = coffee_record(payload={"Name": "Replayed Old Name"}, source_version="3")
        result = bootstrapper.bootstrap(engine_instance_id="erp", legal_entity_id="le-za", records=[stale])

        self.assertEqual(result.updated, 0)
        self.assertEqual(len(result.drift), 1)
        native_id = mappings.values[("erp", "le-za", "product", "prod-1")][0]
        self.assertEqual(client.records[("M_Product", native_id)]["Name"], "Coffee")


if __name__ == "__main__":
    unittest.main()
