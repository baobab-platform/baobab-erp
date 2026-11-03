"""Guard/failure-path source tests; these do not qualify native restoration."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

DRIVER = Path(__file__).resolve().parents[2] / 'idempiere/acceptance/erp-a/driver'
sys.path.insert(0, str(DRIVER))
spec = importlib.util.spec_from_file_location('restore_drill', DRIVER / 'restore_drill.py')
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)
SOURCE = 'a' * 40
ENV = {'BAOBAB_ENVIRONMENT': 'integration', 'ERP_A_PROJECT': 'baobab-erp-a-' + 'a' * 16}


class FailingRestore:
    def __init__(self, exists=False):
        self.commands = []
        self.exists = exists

    def scalar(self, _service, _user, _db, sql):
        return '170010' if sql == 'SHOW server_version_num' else ('1' if self.exists else '0')

    def run(self, *args):
        self.commands.append(args)
        if 'pg_restore' in args:
            raise RuntimeError('private-database-diagnostic')
        return ''


class RestoreFailureTests(unittest.TestCase):
    def test_protected_and_unknown_environments_never_touch_database(self):
        for environment in ('production', 'staging', '', None):
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                drill.identity(environment, ENV['ERP_A_PROJECT'], SOURCE)

    def test_unowned_project_and_mutable_sources_are_refused(self):
        for project, source in (('baobab-gate-d-erp-a', SOURCE),
                                ('baobab-erp-a-../../production', SOURCE),
                                (ENV['ERP_A_PROJECT'], 'main')):
            with self.subTest(project=project), self.assertRaises(ValueError):
                drill.identity('integration', project, source)

    def test_existing_database_is_never_deleted_or_reused(self):
        fake = FailingRestore(exists=True)
        with patch.dict(drill.os.environ, ENV), self.assertRaisesRegex(ValueError, 'ALREADY_EXISTS'):
            drill.drill(fake, SOURCE)
        self.assertEqual([], fake.commands)

    def test_interrupted_restore_drops_only_generated_sibling_and_private_dump(self):
        fake = FailingRestore()
        with patch.dict(drill.os.environ, ENV), patch.object(drill, 'snapshot', return_value={}), \
                patch.object(drill, 'guards', return_value='native-guard'), \
                self.assertRaisesRegex(RuntimeError, 'private-database-diagnostic'):
            drill.drill(fake, SOURCE)
        drops = [args for args in fake.commands if 'dropdb' in args]
        self.assertEqual(1, len(drops))
        self.assertRegex(drops[0][-1], r'^baobab_dev12_[a-f0-9]{32}$')
        removed = [args for args in fake.commands if 'rm' in args]
        self.assertEqual(1, len(removed))
        self.assertRegex(removed[0][-1], r'^/tmp/baobab-dev12-[a-f0-9]{32}\.dump$')

    def test_denial_requires_real_affected_row_and_unchanged_native_readback(self):
        class FalseDenial:
            def scalar(self, *_args):
                return '123'

            def psql(self, *_args, **_kwargs):
                return subprocess.CompletedProcess([], 1, 'BEGIN\nUPDATE 0\n', 'BAOBAB_NATIVE_FINANCE_DENIED')

        with patch.object(drill, 'snapshot', return_value={}), self.assertRaisesRegex(ValueError, 'VETO_MISSING'):
            drill.restored_denial(FalseDenial(), 'test')


if __name__ == '__main__':
    unittest.main()
