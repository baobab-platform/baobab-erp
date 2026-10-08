import unittest

from provisioning.command_state import FAILED_CODE, derive


class CommandStateTests(unittest.TestCase):
    def test_the_command_state_is_a_pure_function_of_its_entities_statuses(self):
        cases = {
            ("planned",): ("accepted", None),
            ("requested", "planned"): ("accepted", None),
            ("validating", "planned"): ("validating", None),
            ("applying",): ("provisioning", None),
            ("applying", "planned"): ("provisioning", None),
            ("planned", "reconciling"): ("provisioning", None),   # one entity has progressed, one has not started
            ("reconciling",): ("reconciling", None),
            ("ready", "reconciling"): ("reconciling", None),
            ("ready", "ready"): ("active", None),
            ("active", "ready"): ("active", None),
            ("failed", "ready"): ("failed", FAILED_CODE),
            ("failed", "applying"): ("failed", FAILED_CODE),
        }
        for statuses, expected in cases.items():
            with self.subTest(statuses):
                self.assertEqual(derive(statuses), expected)
                self.assertEqual(derive(reversed(statuses)), expected)

    def test_failure_carries_a_fixed_code_never_the_entitys_error(self):
        self.assertRegex(FAILED_CODE, r"^[A-Z][A-Z0-9_]*$")
        self.assertLessEqual(len(FAILED_CODE), 96)

    def test_an_empty_or_unknown_set_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            derive([])
        with self.assertRaises(ValueError):
            derive(["ready", "exploded"])


if __name__ == "__main__":
    unittest.main()
