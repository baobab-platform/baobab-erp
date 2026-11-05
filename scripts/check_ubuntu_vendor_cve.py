#!/usr/bin/env python3
"""Fail-closed Trivy/Ubuntu Noble USN-8996-1 reconciliation for ERP's image.

Canonical fixed apt and libapt-pkg6.0t64 in 2.8.4ubuntu0.1 on 2026-11-04:
https://ubuntu.com/security/notices/USN-8996-1
Trivy DB 2026-11-05 temporarily still labels that exact PATCHED version
CVE-2026-109518 HIGH/affected. This is NOT a blanket ignore-unfixed waiver.
All OTHER HIGH/CRITICAL findings fail in the same actual built image.
Only exact OCI Ubuntu Noble plus the two actual dpkg patch identities qualify.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CVE = "CVE-2026-109518"
PATCHED = "2.8.4ubuntu0.1"
PACKAGES = frozenset({"apt", "libapt-pkg6.0t64"})
SEVERITIES = frozenset({"HIGH", "CRITICAL"})


class Refused(Exception):
    pass


def unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("VENDOR_VEX_DUPLICATE_JSON")
        result[key] = value
    return result


def reconcile(raw_scan: bytes, raw_packages: bytes) -> dict[str, object]:
    if len(raw_scan) > 20_000_000 or len(raw_packages) > 512:
        raise Refused("VENDOR_VEX_INPUT_OVERLONG")
    try:
        report = json.loads(raw_scan, object_pairs_hook=unique)
        lines = raw_packages.decode("utf-8").splitlines()
    except (UnicodeError, ValueError, TypeError) as exc:
        raise Refused("VENDOR_VEX_MALFORMED") from exc
    if not isinstance(report, dict) or report.get("ArtifactType") != "container_image":
        raise Refused("VENDOR_VEX_NOT_CONTAINER_SCAN")
    metadata = report.get("Metadata", {})
    os_release = metadata.get("OS", {}) if isinstance(metadata, dict) else {}
    if (not isinstance(os_release, dict) or os_release.get("Family") != "ubuntu"
            or not str(os_release.get("Name", "")).startswith("24.04")):
        raise Refused("VENDOR_VEX_WRONG_OS_RELEASE")
    state = {}
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] in state:
            raise Refused("VENDOR_VEX_AMBIGUOUS_DPKG")
        state[fields[0]] = fields[1]
    if state != {k: PATCHED for k in PACKAGES}:
        raise Refused("VENDOR_VEX_PATCHED_PACKAGE_IDENTITY_MISSING")
    results = report.get("Results")
    if not isinstance(results, list) or len(results) == 0:
        raise Refused("VENDOR_VEX_MISSING_SCAN_RESULTS")
    seen = set()
    adjudicated = 0
    for result in results:
        if not isinstance(result, dict):
            raise Refused("VENDOR_VEX_MALFORMED_RESULTS")
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise Refused("VENDOR_VEX_MALFORMED_RESULTS")
        for finding in vulnerabilities:
            if not isinstance(finding, dict):
                raise Refused("VENDOR_VEX_MALFORMED_RESULTS")
            if finding.get("Severity") not in SEVERITIES:
                continue
            package, version = finding.get("PkgName"), finding.get("InstalledVersion")
            identity = (finding.get("VulnerabilityID"), package, version)
            if identity in seen:
                raise Refused("VENDOR_VEX_DUPLICATE_FINDING")
            seen.add(identity)
            if (finding.get("VulnerabilityID") != CVE
                    or package not in PACKAGES or version != PATCHED):
                raise Refused("VENDOR_VEX_OTHER_HIGH_CRITICAL_FINDING")
            adjudicated += 1
    return {
        "status": "VENDOR_FIXED_EXACT_PATCH",
        "usn": "USN-8996-1",
        "cve": CVE,
        "patched_apt_version": PATCHED,
        "scanner_high_critical_vendor_stale_findings": adjudicated,
        "other_high_critical": 0,
        "scan_scope": "full-built-image",
        "protected_deployment_accepted": False,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_ubuntu_vendor_cve.py SCAN.json PACKAGES.tsv", file=sys.stderr)
        return 2
    try:
        scan = Path(sys.argv[1]).read_bytes()
        packages = Path(sys.argv[2]).read_bytes()
        print(json.dumps(reconcile(scan, packages), sort_keys=True))
    except (Refused, OSError) as exc:
        reason = str(exc) if isinstance(exc, Refused) else "VENDOR_VEX_IO_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
