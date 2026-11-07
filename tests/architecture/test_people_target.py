"""BP-00 non-activation and target-baseline architecture regression."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PeopleArchitectureTests(unittest.TestCase):
    def test_java21_target_pg17_without_premature_runtime_claim(self):
        lock = (ROOT / "upstream.lock.yaml").read_text()
        self.assertIn('target_release: "21"', lock)
        self.assertIn('image: "postgres:17-alpine"', lock)
        self.assertIn('release: "17"', lock, "Runtime is Java17 until live iDempiere Java21 qualification")
        self.assertTrue((ROOT / "docs/people/compatibility-matrix.md").exists())

    def test_only_planned_capabilities_no_people_support(self):
        declaration = (ROOT / ".baobab/capability-provider.yaml").read_text()
        self.assertIn("planned_capabilities:", declaration)
        support, proposed = declaration.split("planned_capabilities:", 1)
        for label in ("workforce.employment.manage", "payroll.run.manage"):
            self.assertIn("proposed_key: " + label, proposed)
            self.assertNotIn("capability_key: " + label, support)
        self.assertIn("proposal_status: PROPOSED", proposed)

    def test_no_people_runtime_registration(self):
        src = (ROOT / "modules/people").resolve()
        self.assertTrue((src / "workforce/service.py").exists())
        self.assertTrue((src / "payroll/service.py").exists())
        self.assertFalse((ROOT / "idempiere/extensions/org.nabhold.baobab.erp.people").exists())
        self.assertFalse((ROOT / "modules/people/api.py").exists())


if __name__ == "__main__":
    unittest.main()
