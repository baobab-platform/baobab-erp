"""ADR-ERP-001: private engine entrypoints are not host-wide published.

The default Compose topology is a development baseline, not a production network
policy. These fitness checks nevertheless prevent an accidental direct publication
of native iDempiere REST/WebUI or the Baobab app facade on all host interfaces.
The actual protected deployment must additionally enforce gateway, IAM and
network controls (ADR-ERP-001 sections 26, 80 and 109).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"


class AdrErp001PrivateBoundaryTests(unittest.TestCase):
    def test_source_cannot_publish_engine_ports_host_wide_by_default(self):
        """Even without Docker installed, require literal loopback bindings."""
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn(
            '"127.0.0.1:${IDEMPIERE_HTTPS_PORT:-8443}:8443"',
            compose,
        )
        self.assertIn(
            '"127.0.0.1:${BAOBAB_APP_PORT:-8000}:8000"',
            compose,
        )
        self.assertNotIn('"${IDEMPIERE_HTTPS_PORT:-8443}:8443"', compose)
        self.assertNotIn('"${BAOBAB_APP_PORT:-8000}:8000"', compose)

    def test_resolved_compose_exposes_no_unrestricted_erp_port(self):
        """Inspect Docker's resolved model, including nondefault host ports."""
        if shutil.which("docker") is None:
            self.skipTest("Docker CLI unavailable; source guard remains enforced")
        check = subprocess.run(
            ["docker", "compose", "version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            self.skipTest("Docker Compose plugin unavailable; source guard remains enforced")

        env = os.environ.copy()
        env.update(
            DB_PASS="adr001-test-only",
            DB_ADMIN_PASS="adr001-test-only",
            BAOBAB_EVENT_SIGNING_SECRET="adr001-test-only",
            BAOBAB_IAM_OIDC_ISSUER="https://iam.invalid/realms/baobab",
            IDEMPIERE_HTTPS_PORT="18443",
            BAOBAB_APP_PORT="18000",
        )
        output = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config", "--format", "json"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        services = json.loads(output.stdout)["services"]
        self.assertFalse(services["postgres"].get("ports", []), "ERP DB must not be host-published")
        for service_name, target, published in (
            ("idempiere", 8443, "18443"),
            ("baobab-app", 8000, "18000"),
        ):
            with self.subTest(service=service_name):
                service = services[service_name]
                self.assertNotEqual(service.get("network_mode"), "host")
                ports = service.get("ports", [])
                self.assertEqual(len(ports), 1, "only the deliberate operator loopback port is allowed")
                port = ports[0]
                self.assertEqual(port.get("host_ip"), "127.0.0.1")
                self.assertEqual(port.get("target"), target)
                self.assertEqual(str(port.get("published")), published)
                self.assertEqual(port.get("protocol", "tcp"), "tcp")


if __name__ == "__main__":
    unittest.main()
