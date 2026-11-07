"""BA-SEC-DEP-001: source-only ERP/Trade dependency maintenance regression tests.

No network call, no live vulnerability assertion, no protected release approval.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
IS_ERP = (ROOT / "uv.lock").is_file()
REQUIRED = (
    {
        ("github-actions", "/"), ("uv", "/"),
        ("maven", "/idempiere/extensions"),
        ("docker", "/idempiere"), ("docker", "/modules"),
        ("docker-compose", "/"),
        ("docker-compose", "/idempiere/acceptance/erp-a"),
    }
    if IS_ERP
    else {
        ("github-actions", "/"), ("npm", "/"),
        ("docker", "/"), ("docker-compose", "/"),
    }
)


def violations(config: object) -> list[str]:
    """Reject missing manifests, hidden majors and suppressed security settings."""
    errors: list[str] = []
    if not isinstance(config, dict) or config.get("version") != 2:
        return ["version"]
    updates = config.get("updates")
    if not isinstance(updates, list) or not updates:
        return ["updates"]
    seen = set()
    for item in updates:
        if not isinstance(item, dict):
            errors.append("invalid update")
            continue
        eco, d = item.get("package-ecosystem"), item.get("directory")
        if not isinstance(eco, str) or not isinstance(d, str):
            errors.append("missing ecosystem/directory")
            continue
        key = eco, d
        if key in seen:
            errors.append("duplicate manifest entry")
        seen.add(key)
        if not d.startswith("/") or ".." in d.split("/"):
            errors.append("unsafe directory")
            continue
        if "target-branch" in item:
            errors.append("default branch policy override")
        sch = item.get("schedule", {})
        if not isinstance(sch, dict) or (
            sch.get("interval") != "weekly" or sch.get("day") != "monday"
            or sch.get("timezone") != "Africa/Johannesburg" or not sch.get("time")
        ):
            errors.append("unsupported weekly schedule")
        n = item.get("open-pull-requests-limit")
        if type(n) is not int or n < 1:
            errors.append("disabled PR limit")
        if not isinstance(item.get("labels"), list) or not item.get("labels"):
            errors.append("missing labels")
        if not isinstance(item.get("commit-message"), dict) or (
            not item["commit-message"].get("prefix")
        ):
            errors.append("missing commit prefix")
        for group in (item.get("groups") or {}).values():
            if not isinstance(group, dict) or group.get("applies-to") != "version-updates":
                errors.append("unscoped security/version group")
            elif not (
                group.get("patterns") and isinstance(group.get("update-types"), list)
                and set(group["update-types"]).issubset({"minor", "patch"})
                and group["update-types"]
            ):
                errors.append("major/unbounded routine group")
        for ignore in (item.get("ignore") or []):
            if not isinstance(ignore, dict) or not ignore.get("update-types"):
                errors.append("unconditional ignore")
        actual = ROOT / d.lstrip("/")
        if not actual.is_dir():
            errors.append("missing directory")
        elif eco == "github-actions" and not (ROOT / ".github/workflows").is_dir():
            errors.append("missing actions workflows")
        elif eco == "npm" and not (
            (actual / "package.json").is_file() and (actual / "package-lock.json").is_file()
        ):
            errors.append("missing npm lock")
        elif eco == "uv" and not (
            (actual / "pyproject.toml").is_file() and (actual / "uv.lock").is_file()
        ):
            errors.append("missing uv workspace")
        elif eco == "maven" and not (actual / "pom.xml").is_file():
            errors.append("missing Maven reactor")
        elif eco == "docker" and not (actual / "Dockerfile").is_file():
            errors.append("missing Dockerfile")
        elif eco == "docker-compose" and not any(
            (actual / filename).is_file()
            for filename in (
                "compose.yaml", "compose.yml", "docker-compose.yml",
                "docker-compose.yaml",
            )
        ):
            errors.append("missing Compose source")
    if not REQUIRED.issubset(seen):
        errors.append("missing required ecosystem")
    return errors


class DependencyMaintenancePolicyTest(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load(
            (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        )

    def reject(self, error, change):
        candidate = deepcopy(self.config)
        change(candidate)
        self.assertIn(error, violations(candidate))

    def test_current_manifest_coverage(self):
        self.assertEqual([], violations(self.config))

    def test_missing_mandatory_manifest_refused(self):
        self.reject(
            "missing required ecosystem",
            lambda cfg: cfg.update({"updates": [
                e for e in cfg["updates"] if e["package-ecosystem"] != "docker"
            ]}),
        )

    def test_duplicate_manifest_refused(self):
        self.reject("duplicate manifest entry",
                    lambda cfg: cfg["updates"].append(deepcopy(cfg["updates"][0])))

    def test_default_branch_override_refused(self):
        self.reject("default branch policy override",
                    lambda cfg: cfg["updates"][0].update({"target-branch": "main"}))

    def test_unscoped_group_refused(self):
        self.reject("unscoped security/version group",
                    lambda cfg: cfg["updates"][0].update({
                        "groups": {"all": {"patterns": ["*"]}},
                    }))

    def test_automatic_major_group_refused(self):
        self.reject("major/unbounded routine group",
                    lambda cfg: cfg["updates"][0].update({"groups": {
                        "routine": {"patterns": ["*"], "applies-to": "version-updates",
                                    "update-types": ["major", "minor", "patch"]},
                    }}))

    def test_unconditional_ignore_refused(self):
        self.reject("unconditional ignore",
                    lambda cfg: cfg["updates"][0].update({
                        "ignore": [{"dependency-name": "*"}],
                    }))

    def test_pr_limit_zero_refused(self):
        self.reject("disabled PR limit",
                    lambda cfg: cfg["updates"][0].update({
                        "open-pull-requests-limit": 0,
                    }))

    def test_invalid_manifest_directory_refused(self):
        self.reject("missing directory",
                    lambda cfg: cfg["updates"][0].update({
                        "directory": "/unowned-no-manifest",
                    }))

    def test_accepted_shared_validator_pin_and_required_ecosystems(self):
        text = (ROOT / ".github/workflows/enforce-dependabot-config.yml").read_text()
        self.assertIn(
            "enforce-dependabot-config.yml@"
            "31de2bc3dcd56128c019c640dc7e12c10ae9ca69", text
        )
        import re
        actual = re.search(r'required-ecosystems:\s*"([^"]+)"', text)
        self.assertIsNotNone(actual)
        self.assertEqual({e for e, _ in REQUIRED}, set(actual.group(1).split(",")))
        self.assertNotIn('policy-level: "strict"', text)

    def test_security_and_platform_codeowners_present(self):
        path = ROOT / (("CODEOWNERS") if IS_ERP else ".github/CODEOWNERS")
        owners = path.read_text(encoding="utf-8")
        self.assertIn("@baobab-platform/platform-engineering", owners)
        self.assertIn("@baobab-platform/security", owners)
        self.assertIn("dependency-maintenance.md", owners)

    def test_governing_audit_record_maintains_separate_states(self):
        text = (ROOT / "docs/security/dependency-maintenance.md").read_text()
        for word in (
            "BA-SEC-DEP-001", "SOURCE_COMMITTED", "CI_VERIFIED",
            "SECURITY_ALERT_PATH_VERIFIED", "BLOCKED",
        ):
            self.assertIn(word, text)

    def test_source_owned_runtime_and_lockfiles_exist(self):
        if IS_ERP:
            self.assertTrue((ROOT / "modules/pyproject.toml").is_file())
            self.assertTrue((ROOT / "pom.xml").is_file())
            self.assertTrue((ROOT / "idempiere/acceptance/erp-a/compose.yaml").is_file())
        else:
            package = json.loads((ROOT / "package.json").read_text())
            self.assertEqual("npm", package["packageManager"].split("@")[0])
            self.assertTrue((ROOT / "Dockerfile.dev07").is_file())

    @unittest.skipUnless(IS_ERP, "iDempiere specific historical scan suppressions")
    def test_unapproved_legacy_trivy_allowlist_is_not_active(self):
        self.assertFalse((ROOT / ".trivyignore").exists())
        archive = (ROOT / "docs/security/idempiere-legacy-trivy-findings.md").read_text()
        self.assertIn("16 CVE exclusions", archive)
        self.assertIn("NOT ACTIVE", archive)

    @unittest.skipIf(IS_ERP, "Trade exception expiry is owned by Trade")
    def test_trade_security_exceptions_must_not_be_expired(self):
        data = yaml.safe_load((ROOT / ".baobab/repository.yaml").read_text())
        for key in ("dependency-audit", "container-scan"):
            row = data["exceptions"][key]
            expiry = row["expires"]
            if isinstance(expiry, str):
                expiry = date.fromisoformat(expiry)
            self.assertGreaterEqual(
                expiry, date.today(),
                f"{key} expired: BLOCKED; obtain new independent Security evidence",
            )

    @unittest.skipIf(IS_ERP, "Only Trade has an npm-native security audit")
    def test_trade_native_advisory_scan_is_daily_and_full_tree(self):
        workflow = (ROOT / ".github/workflows/security.yml").read_text()
        self.assertIn("npm audit --audit-level=high", workflow)
        self.assertIn('cron: "0 3 * * *"', workflow)

    @unittest.skipUnless(IS_ERP, "ERP Java adapter readiness is tracked separately")
    def test_erp_maven_native_audit_gap_is_disclosed(self):
        record = (ROOT / "docs/security/dependency-maintenance.md").read_text()
        self.assertIn("Java-native", record)
        self.assertIn("not yet verified", record)


if __name__ == "__main__":
    unittest.main()
