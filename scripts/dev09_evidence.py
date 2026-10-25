#!/usr/bin/env python3
"""Sanitised DEV-09 read model of ERP-owned observations, never authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

NATIVE_CASES = tuple([f"S{i:02}" for i in range(1, 27)] + ["S04b", "S22b"]
                     + [f"B{i:02}" for i in range(1, 12)])
BLOCKED = {
    "current-iam-and-cp-joined-authority": "TEST_ISSUER_AND_SYNTHETIC_AUTHORITY_ROWS_ONLY",
    "independent-company-org-isolation": "SECOND_NATIVE_COMPANY_ORG_NOT_EXERCISED",
    "gl-journal-joined-provenance": "SEPARATE_GATE_D_NOT_THIS_PROFILE",
    "subscriptions-internal-current-authority": "SUBSCRIPTIONS_NOT_JOINED",
    "subscriptions-commercial-killbill": "KILL_BILL_ADAPTER_NOT_IMPLEMENTED",
    "payments-simulated-lifecycle": "PAYMENTS_NOT_JOINED",
    "external-provider-settlement": "NO_BANK_OR_PSP_PROVIDER_QUALIFIED",
    "trade-native-commit": "TRADE_NOT_JOINED",
}
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def cleanup(project: str, run: Path) -> dict:
    """Observe only this run's labelled resources after compose down; no deletion."""
    require(re.fullmatch(r"baobab-erp-a-[a-z0-9-]+", project), "run-owned project required")
    remaining = {}
    for resource in ("container", "volume", "network"):
        result = subprocess.run(
            ["docker", resource, "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"],
            check=True, capture_output=True, text=True)
        remaining[resource] = len(result.stdout.split())
    require(not any(remaining.values()) and not run.exists(), "owned resources remain")
    return {"status": "COMPLETE", "scope": "RUN_OWNED_COMPOSE_CONTAINERS_VOLUMES_NETWORKS_AND_TEMP_FILES",
            "project": project, "remaining": remaining, "temporary_directory_removed": True,
            "host_or_image_teardown": False}


def build(native: dict, teardown: dict, source_sha: str, cp_sha: str, run_url: str) -> dict:
    require(SHA.fullmatch(source_sha) and SHA.fullmatch(cp_sha), "exact source/dependency SHA required")
    require(re.fullmatch(r"https://github.com/baobab-platform/baobab-erp/actions/runs/[0-9]+", run_url),
            "owner run URL required")
    require(native.get("candidate") == {"repository": "baobab-platform/baobab-erp", "sha": source_sha},
            "receipt must match executing source")
    require(native.get("dependencies") == {"baobab-cp": cp_sha}, "CP pin mismatch")
    require(native.get("result") == "PASS", "native harness failed")
    pins = native.get("shared_pins", {})
    require(set(pins) == {"contracts.lock.yaml", "lock_sha256"} and SHA.fullmatch(pins.get("contracts.lock.yaml", "")) and
            re.fullmatch(r"[0-9a-f]{64}", pins.get("lock_sha256", "")), "Shared provenance missing")
    images = native.get("images", {})
    require(set(images) == {"erp", "cp", "issuer"} and all(
        DIGEST.fullmatch(image.get("id", "")) for image in images.values()), "built image IDs required")
    scenarios = native.get("scenarios", [])
    require(isinstance(scenarios, list) and len(scenarios) == len(NATIVE_CASES), "native inventory incomplete")
    ids = [case.get("id") for case in scenarios]
    require(len(set(ids)) == len(ids) and set(ids) == set(NATIVE_CASES), "native inventory changed")
    require(all(case.get("result") == "PASS" for case in scenarios), "native case failed or skipped")
    require(set(teardown) == {"status", "scope", "project", "remaining", "temporary_directory_removed",
                              "host_or_image_teardown"}, "closed teardown observation required")
    require(teardown["status"] == "COMPLETE" and teardown["temporary_directory_removed"] is True
            and teardown["host_or_image_teardown"] is False
            and teardown["scope"] == "RUN_OWNED_COMPOSE_CONTAINERS_VOLUMES_NETWORKS_AND_TEMP_FILES"
            and re.fullmatch(r"baobab-erp-a-[a-z0-9-]+", teardown["project"])
            and teardown["remaining"] == {"container": 0, "volume": 0, "network": 0}, "cleanup not complete")
    # Closed projection: provider details, SQL, paths, notes and raw responses never escape.
    cases = [{"case": "erp-a-" + sid.lower(), "result": "PASS", "reason": "PERSISTED_NATIVE_ASSERTION"}
             for sid in NATIVE_CASES]
    cases.append({"case": "owned-resource-teardown", "result": "PASS", "reason": teardown["scope"]})
    cases.extend({"case": name, "result": "BLOCKED", "reason": reason} for name, reason in BLOCKED.items())
    return {"schema": "dev09-erp-component-evidence.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
            "source_sha": source_sha, "cp_sha": cp_sha, "shared_pins": pins,
            "image_ids": {name: image["id"] for name, image in images.items()}, "run_url": run_url,
            "evidence_class": "REAL_COMPONENT_SYNTHETIC_DATA", "environment": "ISOLATED_DEVELOPMENT",
            "scope": "ERP-A/B purchase recording, native persistence and own Compose cleanup; test issuer, synthetic legal rows and payment evidence",
            "int08_qualified": False, "current_iam_qualified": False, "provider_qualified": False,
            "protected_acceptance": False, "production_authorized": False,
            "money_moved": False, "cleanup": teardown,
            "result": "BLOCKED", "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    clean = sub.add_parser("cleanup")
    clean.add_argument("--project", required=True)
    clean.add_argument("--run", type=Path, required=True)
    clean.add_argument("--output", type=Path, required=True)
    report = sub.add_parser("report")
    report.add_argument("--directory", type=Path, required=True)
    report.add_argument("--source-sha", required=True)
    report.add_argument("--cp-sha", required=True)
    report.add_argument("--run-url", required=True)
    args = parser.parse_args()
    if args.command == "cleanup":
        args.output.write_text(json.dumps(cleanup(args.project, args.run), indent=2) + "\n")
    else:
        root = args.directory
        # Remove old outputs before any input validation; a failed rerun cannot expose stale success.
        target, hashed = root / "dev09-report.json", root / "dev09-report.sha256.json"
        target.unlink(missing_ok=True)
        hashed.unlink(missing_ok=True)
        result = build(read(root / "erp-a-receipt.json"), read(root / "dev09-cleanup.json"),
                       args.source_sha, args.cp_sha, args.run_url)
        raw = (json.dumps(result, indent=2) + "\n").encode()
        target.write_bytes(raw)
        hashed.write_text(json.dumps({"file": target.name, "sha256": hashlib.sha256(raw).hexdigest()}, indent=2) + "\n")


if __name__ == "__main__":
    main()
