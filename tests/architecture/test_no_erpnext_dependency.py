"""Architecture fitness function (Phase 30): there must be zero production references
to ERPNext, Frappe, or Bench left in this repository. A small, explicit allowlist
covers the historical/migration documentation that is expected to name them.
"""

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Historical/migration documentation is expected to discuss the retired ERPNext
# scaffold by name; everything else must be clean. Paths are repo-relative.
ALLOWED_PREFIXES = (
    "docs/migration/",
    "migration/",
    "tests/migration/",
    "docs/adr/ADR-0001-upstream-extension-model.md",
    "docs/adr/ADR-0002-site-tenancy.md",
    "docs/adr/ADR-0003-canonical-mappings.md",
    "docs/adr/ADR-0004-integration-transport.md",
    "docs/adr/ADR-0005-database.md",
    "docs/adr/README.md",
    "CHANGELOG.md",
    "README.md",
    "tests/architecture/test_no_erpnext_dependency.py",
)

# ADR-SHARED-045 permanent BYOP permits a physically separate external
# Frappe HR REST *consumer*, not ERPNext-as-ERP, Bench orchestration or
# imports into the native iDempiere application. The exception is EXACT;
# another ERPNext/Frappe reference anywhere still fails this fitness gate.
OPTIONAL_EXTERNAL_PEOPLE_ADAPTER_FILES = frozenset({
    "modules/people/providers/frappe_hr.py",
    "tests/unit/test_people_frappe_hr.py",
    "docs/people/README.md",
    "docs/people/frappe-hr-read-adapter.md",
})

PATTERN = re.compile(r"\b(erpnext|frappe|bench)\b", re.IGNORECASE)
FORBIDDEN_NATIVE_IMPORT = re.compile(
    r"(?m)^\s*(?:from\s+(?:frappe|erpnext)\b|import\s+(?:frappe|erpnext)\b)"
)



def _tracked_files() -> list[str]:
    result = subprocess.run(
        # -c safe.directory=* avoids "detected dubious ownership" when this runs
        # against a repo checked out by a different user/UID (e.g. a CI container
        # with the workspace bind-mounted in), without touching global git config.
        ["git", "-c", "safe.directory=*", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


class NoErpnextDependencyTests(unittest.TestCase):
    def test_no_unexpected_erpnext_frappe_bench_references(self):
        violations = []
        for relative_path in _tracked_files():
            if relative_path.startswith(ALLOWED_PREFIXES):
                continue
            if relative_path in OPTIONAL_EXTERNAL_PEOPLE_ADAPTER_FILES:
                # This pair may describe the external wire protocol by
                # name; importing the retired ERP engine is still forbidden.
                optional_source = (REPO_ROOT / relative_path).read_text(errors="ignore")
                if (FORBIDDEN_NATIVE_IMPORT.search(optional_source)
                        or "erpnext" in optional_source.lower()
                        or "bench" in optional_source.lower()):
                    violations.append(relative_path)
                continue
            path = REPO_ROOT / relative_path
            try:
                text = path.read_text(errors="ignore")
            except (UnicodeDecodeError, IsADirectoryError, OSError):
                continue
            if PATTERN.search(text):
                violations.append(relative_path)

        self.assertEqual(
            violations,
            [],
            "Unexpected ERPNext/Frappe/Bench reference outside the historical-documentation "
            f"allowlist: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
