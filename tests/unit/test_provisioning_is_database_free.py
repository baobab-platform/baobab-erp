import os
import subprocess
import sys
import unittest

# The unit suite runs without a database driver (CI `validate`). Anything the provisioning domain imports must stay
# importable without one: Postgres belongs in *_store modules, which only the integration suite imports.
DOMAIN_MODULES = (
    "provisioning.authoritative_service", "provisioning.cp_contract", "provisioning.finance_baseline",
    "provisioning.legal_entity_policy", "provisioning.model", "provisioning.planner", "provisioning.validation",
    # The service and its store protocol, and the pure parts of the event path (FB-04b).
    "provisioning.service", "provisioning.store", "provisioning.command_state", "provisioning.command_events",
    "integration.signed_delivery", "outbox.service",
    # Execution: the executor and everything it decides with. The Postgres side is provisioning.execution_store.
    "provisioning.execution", "provisioning.native_processes", "provisioning.request_state", "provisioning.idempiere_adapter",
)


class ProvisioningDomainIsDatabaseFreeTests(unittest.TestCase):
    def test_domain_modules_import_without_a_database_driver(self):
        for module in DOMAIN_MODULES:
            with self.subTest(module):
                result = subprocess.run(
                    [sys.executable, "-c", f"import sys; sys.modules['psycopg'] = None; import {module}"],
                    env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-400:])


if __name__ == "__main__":
    unittest.main()
