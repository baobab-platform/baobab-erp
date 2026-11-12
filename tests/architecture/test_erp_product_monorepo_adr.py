"""ADR-ERP-025 repository governance guard: accepted design != activated runtime.

This intentionally checks documentation and architectural semantics only; it
never claims independent providers, product capabilities, or engine swaps are
implemented or production-qualified.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = ROOT / "docs/adr/ADR-ERP-025 — Autonomous Enterprise Product Monorepo and Replaceable Engine Architecture.md"


class ERPProductMonorepoArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adr = ADR_PATH.read_text(encoding="utf-8")
        cls.index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
        cls.ledger = (ROOT / "architecture/conformance.yaml").read_text(encoding="utf-8")

    def test_accepted_adr_indexed_and_tracked_as_not_yet_implemented(self):
        self.assertIn("**Status:** **Accepted", self.adr)
        self.assertIn("ADR-ERP-025", self.index)
        block = self.ledger.split("  - id: ADR-ERP-025\n", 1)[1]
        self.assertIn("    status: planned\n", block)
        self.assertIn("ERP-MONO-00", block)
        self.assertIn("NOT implemented or certified", block)
        self.assertIn("No physical code relocation", block)

    def test_products_and_candidates_have_explicit_governance(self):
        for product in (
            "Baobab Finance", "Baobab People", "Baobab WMS",
            "Baobab Manufacturing", "Baobab Supply Chain Management",
            "Baobab CRM", "Baobab Assets", "Baobab Projects",
            "Baobab Quality", "Baobab Service Management",
        ):
            with self.subTest(product=product):
                self.assertIn(product, self.adr)
        self.assertIn("candidate product boundaries", self.adr)
        self.assertIn("product-admission", self.adr.lower())

    def test_replaceable_provider_and_current_native_financial_veto(self):
        for expected in (
            "iDempiere 13 is the currently selected",
            "not a permanently mandated vendor",
            "replaceable anti-corruption adapter",
            "CP binding generation",
            "No replay through a second provider",
            "ADR-ERP-022",
            "ERP-MONO-04",
            "ERP-MONO-06",
            "ERP-MONO-12",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.adr)

    def test_not_a_runtime_activation_or_data_migration(self):
        self.assertIn("No physical split or rename", self.adr)
        self.assertIn("does not install a provider", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("ADR-ERP-023", self.adr)
        self.assertIn("ADR-ERP-024", self.adr)
        self.assertIn("ADR-ERP-015", self.adr)
        self.assertIn("ERP #116", self.adr)
        self.assertIn("ERP #117", self.adr)


if __name__ == "__main__":
    unittest.main()
