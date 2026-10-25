"""Pinned Ory config preparation must preserve distinct browser origins."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "dev09_ory_bootstrap", ROOT / "idempiere/acceptance/erp-a/driver/ory_bootstrap.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class OryConfigTest(unittest.TestCase):
    def test_distinct_pinned_origins_survive_runtime_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            iam = root / "iam"
            source = iam / "config/ory"
            (source / "hydra").mkdir(parents=True)
            (source / "kratos").mkdir()
            (source / "hydra/hydra.yml").write_text(
                "strategies:\n  access_token: jwt\noauth2:\n  expose_internal_errors: false\n"
                "secrets:\n - local_dev_only_hydra_system_secret_change_me\n"
                " - local_dev_only_pairwise_salt_change_me\n")
            (source / "kratos/kratos.yml").write_text(
                "allowed_origins:\n - http://127.0.0.1:3000\n - http://127.0.0.1:4455\n"
                "allowed_return_urls:\n - http://127.0.0.1:4455\n - http://127.0.0.1:3000\n"
                "default_browser_return_url: http://127.0.0.1:4455/\n")
            (source / "kratos/identity.schema.json").write_text('{}')
            run = root / "run"
            sha = 'a' * 40
            with patch.object(mod.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, sha+'\n')), \
                    patch.dict(os.environ, ORY_SYSTEM_SECRET='s'*48, ORY_HOOK_SECRET='h'*48):
                mod.prepare(run, iam, sha)
            prepared = (run / 'ory/kratos/kratos.yml').read_text()
            for block in ('allowed_origins', 'allowed_return_urls'):
                origins = prepared.split(block+':\n')[1].split('\n', 2)[:2]
                self.assertEqual(2, len(set(origins)))
                self.assertEqual({' - https://rp.gated.test', ' - https://selfservice.gated.test'}, set(origins))
            self.assertIn('default_browser_return_url: https://selfservice.gated.test/', prepared)
            self.assertNotIn('127.0.0.1', prepared)


if __name__ == '__main__':
    unittest.main()
