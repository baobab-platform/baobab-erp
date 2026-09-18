import unittest
from datetime import date

from provisioning.localisation import CertifiedLocalisation, LocalisationError, LocalisationRegistry
from provisioning.localisation_adapter import LocalisationProvisioner


class FakeClient:
    def __init__(self):
        self.executed = []

    def execute_process(self, process_id, parameters):
        self.executed.append((process_id, parameters))
        return {"process_id": process_id, "ok": True}


def za_profile(**overrides) -> CertifiedLocalisation:
    defaults = dict(
        profile_id="zuribeans-za-certified-v1", country_code="ZA", version="1",
        effective_from=date(2026, 1, 1), effective_to=None, process_id=100,
        certification_reference="FIN-TAX-CERT-ZA-001",
    )
    defaults.update(overrides)
    return CertifiedLocalisation(**defaults)


class LocalisationRegistryTests(unittest.TestCase):
    def test_country_mismatch_fails_closed(self):
        registry = LocalisationRegistry({"za": za_profile()})
        with self.assertRaises(LocalisationError):
            registry.require("za", country_code="UG", on=date(2026, 9, 1))

    def test_certified_effective_profile_resolves(self):
        profile = za_profile(profile_id="ug", country_code="UG")
        registry = LocalisationRegistry({"ug": profile})
        self.assertEqual(registry.require("ug", country_code="UG", on=date(2026, 9, 1)), profile)

    def test_unknown_profile_fails_closed(self):
        registry = LocalisationRegistry({})
        with self.assertRaises(LocalisationError):
            registry.require("missing", country_code="ZA", on=date(2026, 9, 1))

    def test_uncertified_profile_fails_closed(self):
        registry = LocalisationRegistry({"za": za_profile(certification_reference="")})
        with self.assertRaises(LocalisationError):
            registry.require("za", country_code="ZA", on=date(2026, 9, 1))

    def test_not_yet_effective_profile_fails_closed(self):
        registry = LocalisationRegistry({"za": za_profile(effective_from=date(2027, 1, 1))})
        with self.assertRaises(LocalisationError):
            registry.require("za", country_code="ZA", on=date(2026, 9, 1))

    def test_expired_profile_fails_closed(self):
        registry = LocalisationRegistry({"za": za_profile(effective_to=date(2026, 6, 1))})
        with self.assertRaises(LocalisationError):
            registry.require("za", country_code="ZA", on=date(2026, 9, 1))

    def test_missing_process_id_fails_closed(self):
        registry = LocalisationRegistry({"za": za_profile(process_id=0)})
        with self.assertRaises(LocalisationError):
            registry.require("za", country_code="ZA", on=date(2026, 9, 1))


class LocalisationProvisionerTests(unittest.TestCase):
    def test_apply_invokes_the_certified_profiles_native_process(self):
        client = FakeClient()
        registry = LocalisationRegistry({"za": za_profile()})
        provisioner = LocalisationProvisioner(client=client, registry=registry)

        result = provisioner.apply(
            profile_id="za", country_code="ZA", effective_date=date(2026, 9, 1), parameters={"foo": "bar"},
        )

        self.assertEqual(result["process_id"], 100)
        self.assertEqual(len(client.executed), 1)
        process_id, payload = client.executed[0]
        self.assertEqual(process_id, 100)
        self.assertEqual(payload["country_code"], "ZA")
        self.assertEqual(payload["localisation_profile"], "zuribeans-za-certified-v1")
        self.assertEqual(payload["foo"], "bar")

    def test_apply_fails_closed_for_wrong_country(self):
        client = FakeClient()
        registry = LocalisationRegistry({"za": za_profile()})
        provisioner = LocalisationProvisioner(client=client, registry=registry)

        with self.assertRaises(LocalisationError):
            provisioner.apply(profile_id="za", country_code="UG", effective_date=date(2026, 9, 1), parameters={})
        self.assertEqual(client.executed, [])


if __name__ == "__main__":
    unittest.main()
