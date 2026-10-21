"""Architecture guard for the repository-wide PostgreSQL 17 baseline.

The image tags are development/CI defaults, not evidence that an existing
PostgreSQL 16 data directory was upgraded or production was certified.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class Postgres17BaselineTests(unittest.TestCase):
    def test_supported_runtime_and_ci_images(self):
        paths = (
            "compose.yaml",
            ".devcontainer/docker-compose.yml",
            ".github/workflows/ci.yml",
            "upstream.lock.yaml",
        )
        for path in paths:
            data = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("postgres:17-alpine", data)
                self.assertNotIn("postgres:16-alpine", data)

    def test_acceptance_default_and_operator_runbook(self):
        path = ROOT / "idempiere/acceptance/run-gate-d.sh"
        self.assertTrue(path.stat().st_mode & 0o111, "CI invokes the harness directly")
        harness = path.read_text(encoding="utf-8")
        self.assertIn("GATE_D_PG_IMAGE:-postgres:17-alpine", harness)
        self.assertTrue((ROOT / "docs/operations/postgresql-17-upgrade.md").is_file())

    def test_lockfile_declares_pg17_and_idempiere13(self):
        lock = (ROOT / "upstream.lock.yaml").read_text(encoding="utf-8")
        self.assertIn('image: "idempiereofficial/idempiere:13-release"', lock)
        self.assertIn('image: "postgres:17-alpine"', lock)


if __name__ == "__main__":
    unittest.main()
