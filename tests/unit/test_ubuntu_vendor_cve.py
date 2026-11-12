"""Noble USN-8996-1 verification never suppresses another serious CVE."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_ubuntu_vendor_cve import Refused, reconcile  # noqa: E402


def source(findings=None, *, osname="24.04", family="ubuntu"):
    return json.dumps({
        "ArtifactType": "container_image",
        "Metadata": {"OS": {"Family": family, "Name": osname}},
        "Results": [{"Target": "Ubuntu 24.04", "Vulnerabilities": findings or []}],
    }).encode()


def finding(cve="CVE-2026-109518", package="apt", version="2.8.4ubuntu0.1",
            severity="HIGH"):
    return {
        "VulnerabilityID": cve, "PkgName": package,
        "InstalledVersion": version, "Severity": severity,
    }


PATCHES = b"apt\t2.8.4ubuntu0.1\nlibapt-pkg6.0t64\t2.8.4ubuntu0.1\n"


class VendorPatchedCveTest(unittest.TestCase):
    def test_exact_noble_patch_with_either_or_both_scanner_stale_entries(self):
        for findings in ([], [finding()],
                         [finding(), finding(package="libapt-pkg6.0t64")]):
            with self.subTest(findings=findings):
                verdict = reconcile(source(findings), PATCHES)
                self.assertEqual(verdict["status"], "VENDOR_FIXED_EXACT_PATCH")
                self.assertEqual(verdict["other_high_critical"], 0)
                self.assertFalse(verdict["protected_deployment_accepted"])

    def test_every_other_high_or_critical_fails_without_broad_waiver(self):
        for adversarial in (
            finding(cve="CVE-2026-OTHER"),
            finding(package="openssl"),
            finding(version="2.8.3"),
            finding(severity="CRITICAL", package="libapt-pkg6.0t64",
                    cve="CVE-2026-UNKNOWN"),
        ):
            with self.subTest(finding=adversarial), self.assertRaises(Refused):
                reconcile(source([finding(), adversarial]), PATCHES)

    def test_security_failure_identifies_real_advisory_without_dumping_raw_scan(self):
        bad = finding(cve="CVE-2026-OTHER", package="org.example.library",
                      version="1.2.3", severity="CRITICAL")
        bad["FixedVersion"] = "1.2.4"
        with self.assertRaises(Refused) as ctx:
            reconcile(source([finding(), bad]), PATCHES)
        reason = str(ctx.exception)
        self.assertIn("VENDOR_VEX_OTHER_HIGH_CRITICAL_FINDING", reason)
        self.assertIn("id=CVE-2026-OTHER", reason)
        self.assertIn("package=org.example.library", reason)
        self.assertIn("installed=1.2.3", reason)
        self.assertIn("fixed=1.2.4", reason)
        self.assertIn("severity=CRITICAL", reason)

    def test_untrusted_scanner_metadata_is_redacted_in_failure(self):
        bad = finding(cve="CVE-2026-OTHER", package="bad\\nsecret=not-for-logs")
        with self.assertRaises(Refused) as ctx:
            reconcile(source([bad]), PATCHES)
        reason = str(ctx.exception)
        self.assertIn("package=REDACTED", reason)
        self.assertNotIn("not-for-logs", reason)

    def test_no_ubuntu_noble_or_unpatched_apt_cannot_qualify(self):
        for scan, packages in (
            (source([finding()], osname="26.04"), PATCHES),
            (source([finding()], family="debian"), PATCHES),
            (source([finding()]), b"apt\t2.8.3\nlibapt-pkg6.0t64\t2.8.3\n"),
            (source([finding()]), b"apt\t2.8.4ubuntu0.1\n"),
            (source([finding()]), PATCHES + b"apt\t2.8.4ubuntu0.1\n"),
        ):
            with self.subTest(scan=scan, packages=packages), self.assertRaises(Refused):
                reconcile(scan, packages)

    def test_ambiguous_malformed_oversized_or_empty_proof_fails(self):
        cases = (
            (b'{"ArtifactType":"container_image","ArtifactType":"container_image"}', PATCHES),
            (source([finding(), finding()]), PATCHES),
            (source(), b""),
            (source(), b"\xff"),
            (json.dumps({"ArtifactType": "container_image",
                         "Metadata": {"OS": {"Family": "ubuntu", "Name": "24.04"}},
                         "Results": []}).encode(), PATCHES),
            (source(), PATCHES + b"x" * 600),
            (source() + b"x" * 20_000_000, PATCHES),
        )
        for scan, packages in cases:
            with self.subTest(length=len(scan)), self.assertRaises(Refused):
                reconcile(scan, packages)


if __name__ == "__main__":
    unittest.main()
