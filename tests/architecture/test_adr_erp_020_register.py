"""ADR-ERP-020 fitness gate: every accepted ERP ADR must have one auditable entry.

This validates coverage and evidence-path existence, *not* runtime conformance.
It intentionally rejects a fake 'complete' status: the status vocabulary is
foundation/partial/planned until independently approved acceptance is modeled.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "architecture/conformance.yaml"
ADR_DIRECTORY = ROOT / "docs/adr"
ID = re.compile(r"ADR-ERP-(\d{3})")
ROW = re.compile(r"^  - id: (ADR-ERP-\d{3})$", re.MULTILINE)
STATUS = re.compile(r"^    status: (foundation|partial|planned)$", re.MULTILINE)


class ErpConformanceInventoryTests(unittest.TestCase):
    def test_each_accepted_decision_has_one_entry(self):
        docs = sorted(
            path for path in ADR_DIRECTORY.glob("ADR-ERP-*")
            if path.is_file() and ID.search(path.name)
        )
        ids = [ID.search(p.name).group(0) for p in docs]
        self.assertEqual(ids, [f"ADR-ERP-{n:03d}" for n in range(1, 24)])
        for path in docs:
            with self.subTest(path=path.name):
                self.assertIn("**Status:** Accepted", path.read_text(encoding="utf-8"))

        register = LEDGER.read_text(encoding="utf-8")
        rows = ROW.findall(register)
        self.assertEqual(len(rows), len(set(rows)), "ADR rows must not repeat")
        self.assertEqual(sorted(rows), ids, "accepted ADRs require explicit conformance entries")

        for match in ROW.finditer(register):
            start = match.end()
            next_row = ROW.search(register, start)
            entry = register[start:next_row.start() if next_row else len(register)]
            with self.subTest(adr=match.group(1)):
                statuses = STATUS.findall(entry)
                self.assertEqual(len(statuses), 1, "one honest, supported conformance status")
                self.assertIn("    evidence:", entry)
                self.assertIn("    gap:", entry)

    def test_draft_native_and_people_extensions_do_not_claim_acceptance(self):
        ledger = LEDGER.read_text(encoding="utf-8")
        for adr, phrases in {
            "ADR-ERP-022": ("status: partial", "ERP #132", "DRAFT", "Fact_Acct"),
            "ADR-ERP-023": ("status: partial", "ERP #126", "DRAFT", "provider"),
        }.items():
            with self.subTest(adr=adr):
                part = ledger.split(f"  - id: {adr}\n", 1)[1].split("\n  - id:", 1)[0]
                for phrase in phrases:
                    self.assertIn(phrase, part)


if __name__ == "__main__":
    unittest.main()
