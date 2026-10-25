"""Failure-path regressions for engineering receipts, never native proof."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev09_evidence.py"
spec = importlib.util.spec_from_file_location("dev09_evidence", SCRIPT)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
SHA = "a" * 40
CP = "b" * 40
URL = "https://github.com/baobab-platform/baobab-erp/actions/runs/123"


class Dev09EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.native = {
            "candidate": {"repository": "baobab-platform/baobab-erp", "sha": SHA},
            "dependencies": {"baobab-cp": CP}, "result": "PASS",
            "shared_pins": {"contracts.lock.yaml": "c" * 40, "lock_sha256": "d" * 64},
            "images": {k: {"id": "sha256:" + "e" * 64} for k in ("erp", "cp", "issuer")},
            "scenarios": [{"id": sid, "result": "PASS", "detail": "credential-must-not-escape"}
                          for sid in evidence.NATIVE_CASES],
            "notes": ["credential-must-not-escape"],
        }
        self.cleanup = {"status": "COMPLETE", "scope": "RUN_OWNED_COMPOSE_CONTAINERS_VOLUMES_NETWORKS_AND_TEMP_FILES",
                        "project": "baobab-erp-a-abc123", "remaining": {"container": 0, "volume": 0, "network": 0},
                        "temporary_directory_removed": True, "host_or_image_teardown": False}

    def test_native_success_preserves_joined_blockers_and_sanitises(self):
        report = evidence.build(self.native, self.cleanup, SHA, CP, URL)
        self.assertEqual(40, sum(c["result"] == "PASS" for c in report["cases"]))
        self.assertEqual(8, sum(c["result"] == "BLOCKED" for c in report["cases"]))
        self.assertEqual("BLOCKED", report["result"])
        self.assertNotIn("credential-must-not-escape", json.dumps(report))
        for flag in ("money_moved", "int08_qualified", "current_iam_qualified", "provider_qualified",
                     "protected_acceptance", "production_authorized"):
            self.assertIs(report[flag], False)

    def test_missing_duplicate_unknown_failed_and_skipped_cases_refused(self):
        for transform in (lambda s: s.pop(), lambda s: s.append(s[0]),
                          lambda s: s[0].update(id="S00"), lambda s: s[0].update(result="FAIL"),
                          lambda s: s[0].update(result="SKIPPED"), lambda s: s.clear()):
            with self.subTest(transform=transform):
                native = copy.deepcopy(self.native)
                transform(native["scenarios"])
                with self.assertRaises(ValueError):
                    evidence.build(native, self.cleanup, SHA, CP, URL)

    def test_unbound_source_dependency_and_images_refused(self):
        for path, value in (("candidate", {}), ("dependencies", {}), ("images", {}),
                            ("shared_pins", {}), ("result", "FAIL")):
            with self.subTest(path=path):
                native = copy.deepcopy(self.native)
                native[path] = value
                with self.assertRaises(ValueError):
                    evidence.build(native, self.cleanup, SHA, CP, URL)
        self.native["shared_pins"]["raw_secret"] = "must not escape"
        with self.assertRaises(ValueError):
            evidence.build(self.native, self.cleanup, SHA, CP, URL)

    def test_incomplete_or_broadened_cleanup_refused(self):
        for key, value in (("status", "NOT_OBSERVED"), ("temporary_directory_removed", False),
                           ("host_or_image_teardown", True), ("remaining", {"container": 1}),
                           ("scope", "WHOLE_HOST")):
            clean = copy.deepcopy(self.cleanup)
            clean[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.build(self.native, clean, SHA, CP, URL)

    def test_docker_failure_or_surviving_resources_cannot_attest_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = Path(tmp) / "removed"
            with patch.object(evidence.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "docker")):
                with self.assertRaises(subprocess.CalledProcessError):
                    evidence.cleanup("baobab-erp-a-abc", absent)
            with patch.object(evidence.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "leftover\n")):
                with self.assertRaises(ValueError):
                    evidence.cleanup("baobab-erp-a-abc", absent)

    def test_failed_rerun_removes_stale_outputs_and_duplicate_fields_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in ("dev09-report.json", "dev09-report.sha256.json"):
                (root / filename).write_text("stale")
            (root / "erp-a-receipt.json").write_text('{"result":"PASS","result":"FAIL"}')
            result = subprocess.run([sys.executable, str(SCRIPT), "report", "--directory", tmp,
                                     "--source-sha", SHA, "--cp-sha", CP, "--run-url", URL], capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((root / "dev09-report.json").exists())
            self.assertFalse((root / "dev09-report.sha256.json").exists())


if __name__ == "__main__":
    unittest.main()
