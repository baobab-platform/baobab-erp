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
        support, planned = declaration.split("planned_capabilities:", 1)
        # ADR-SHARED-045 is now accepted in Shared. Contracted capability
        # proposals are not executable, and must not become provider support
        # without an independent native or BYOP qualification.
        for label in (
            "workforce.employment.manage",
            "workforce.employment.read",
            "payroll.run.read",
            "payroll.evidence.attest",
        ):
            self.assertIn("capability_key: " + label, planned)
            self.assertNotIn("capability_key: " + label, support)
        self.assertIn("proposal_status: CONTRACTED", planned)
        self.assertNotIn("proposal_status: PROPOSED", planned)
        self.assertNotIn("payroll.run.manage", planned)
        # No nominated native People provider can become a silent default.
        for block in planned.split("  - capability_key: "):
            if block.startswith(("workforce.", "payroll.")):
                self.assertNotIn("target_provider_key:", block)

    def test_provider_neutrality_retains_tenant_choice_without_activating_provider(self):
        policy = (ROOT / "docs/people/provider-neutrality.md").read_text()
        adr = next((ROOT / "docs/adr").glob("ADR-ERP-023*")).read_text()
        intro = (ROOT / "docs/people/README.md").read_text()
        for statement in (
            "Bring Your Own Provider",
            "External-only",
            "lawful export",
            "no automatic native fallback",
            "BYOP-01",
            "BYOP-12",
            "not yet",
        ):
            self.assertIn(statement.lower(), policy.lower())
        self.assertIn("permanent tenant choice", adr.lower())
        self.assertIn("external-only", adr.lower())
        self.assertIn("BYOP", intro)
        provider = (ROOT / ".baobab/capability-provider.yaml").read_text()
        # Architectural eligibility is documentation only; never certify an
        # external HR/payroll provider by merely adding this acceptance plan.
        self.assertNotIn("capability_key: workforce.employment.manage", provider.split("planned_capabilities:", 1)[0])
        self.assertNotIn("capability_key: payroll.run.manage", provider.split("planned_capabilities:", 1)[0])

    def test_protected_runtime_never_auto_installs_people_experiment(self):
        """Development merge must not silently activate People at boot."""
        default_migration = (ROOT / "db/migrate.sh").read_text()
        experimental = (ROOT / "db/migrate-people-experimental.sh").read_text()
        self.assertNotIn("migrate-people-experimental.sh", default_migration)
        self.assertIn('BAOBAB_PEOPLE_EXPERIMENTAL:-', experimental)
        self.assertIn('BAOBAB_ENVIRONMENT:-', experimental)
        self.assertIn('^(test|development|integration)
        src = (ROOT / "modules/people").resolve()
        self.assertTrue((src / "workforce/service.py").exists())
        self.assertTrue((src / "payroll/service.py").exists())
        self.assertFalse((ROOT / "idempiere/extensions/org.nabhold.baobab.erp.people").exists())
        self.assertFalse((ROOT / "modules/people/api.py").exists())


if __name__ == "__main__":
    unittest.main()
, experimental)
        self.assertIn('BAOBAB_PEOPLE_DENIED', experimental)
        self.assertIn("check-people-experimental.sql", experimental)

    def test_no_people_runtime_registration(self):
        src = (ROOT / "modules/people").resolve()
        self.assertTrue((src / "workforce/service.py").exists())
        self.assertTrue((src / "payroll/service.py").exists())
        self.assertFalse((ROOT / "idempiere/extensions/org.nabhold.baobab.erp.people").exists())
        self.assertFalse((ROOT / "modules/people/api.py").exists())


if __name__ == "__main__":
    unittest.main()
