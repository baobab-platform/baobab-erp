"""DEV-09 connected component receipt refuses incomplete, forged or stale proof."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dev09_connected", HERE / "scripts/dev09_connected_evidence.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA = "f" * 40


class ConnectedEvidenceTest(unittest.TestCase):
    def put(self, root, *, overrides=None):
        for name, expected in mod.REQUIRED.items():
            row = dict(expected)
            if name == "dev09-ory-provision.json":
                row["iam_source_sha"] = SHA
            row.update((overrides or {}).get(name, {}))
            (root / name).write_text(json.dumps(row))

    def test_expected_three_observations_remain_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root)
            receipt = mod.build(root, SHA, SHA, SHA)
            self.assertEqual("BLOCKED", receipt["result"])
            self.assertFalse(receipt["full_dev09_qualified"])
            self.assertEqual(4, sum(c["result"] == "PASS" for c in receipt["cases"]))

    def test_missing_observation_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root)
            (root / "dev09-native-company.json").unlink()
            with self.assertRaises(ValueError):
                mod.build(root, SHA, SHA, SHA)

    def test_false_or_stringly_qualified_refuses(self):
        for observed in (False, "true", 1, None):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.put(root, overrides={
                    "dev09-ory-consumption.json": {"mixed_tenant_org_denied": observed}
                })
                with self.assertRaises(ValueError):
                    mod.build(root, SHA, SHA, SHA)

    def test_iam_pin_refuses_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root, overrides={
                "dev09-ory-provision.json": {"iam_source_sha": "a" * 40}
            })
            with self.assertRaisesRegex(ValueError, "SOURCE_MISMATCH"):
                mod.build(root, SHA, SHA, SHA)

    def test_symlink_and_duplicate_fields_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.put(root)
            evidence = root / "dev09-native-company.json"
            evidence.unlink()
            evidence.symlink_to(root / "dev09-ory-consumption.json")
            with self.assertRaises(ValueError):
                mod.build(root, SHA, SHA, SHA)
            evidence.unlink()
            evidence.write_text('{"schema":"x","schema":"y"}')
            with self.assertRaisesRegex(ValueError, "DUPLICATE"):
                mod.build(root, SHA, SHA, SHA)


if __name__ == "__main__":
    unittest.main()
