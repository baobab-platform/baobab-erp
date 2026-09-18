import unittest

from provisioning.zuribeans_entities import ZURIBEANS_UG, ZURIBEANS_ZA, require_supported_legal_entity


class ZuribeansEntitiesTests(unittest.TestCase):
    def test_za_and_ug_are_supported(self):
        self.assertEqual(require_supported_legal_entity(ZURIBEANS_ZA), ZURIBEANS_ZA)
        self.assertEqual(require_supported_legal_entity(ZURIBEANS_UG), ZURIBEANS_UG)

    def test_unsupported_entity_fails_closed(self):
        with self.assertRaises(ValueError):
            require_supported_legal_entity("Thamani")


if __name__ == "__main__":
    unittest.main()
