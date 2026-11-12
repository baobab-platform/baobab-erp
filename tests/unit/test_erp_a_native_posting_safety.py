"""ERP-A native posting errors cannot be confused with successful posting.

The real ERP-A gate independently witnesses PostgreSQL/iDempiere effects.
These unit cases protect interpretation of the JVM file-driver response.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "idempiere" / "acceptance" / "erp-a" / "driver"))

from erpalib import native_post_clean, native_post_outcome_class  # noqa: E402


class NativePostingSafetyTests(unittest.TestCase):
    def test_native_jvm_driver_errors_are_not_successful_replays(self):
        for result in (
            {"driver_error": "java.lang.IllegalArgumentException: unsupported native posting source"},
            {"driver_error": "timeout"},
            {"driver_error": "java.lang.RuntimeException"},
            {"error": "SQL operation failed"},
            {"post_error": "posting returned an error"},
        ):
            with self.subTest(result=result):
                self.assertFalse(native_post_clean(result))
        self.assertEqual(native_post_outcome_class(
            {"driver_error": "java.lang.IllegalArgumentException: unsupported native posting source"}
        ), "UNSUPPORTED_NATIVE_POSTING_SOURCE")
        self.assertEqual(native_post_outcome_class(
            {"driver_error": "timeout"}
        ), "NATIVE_DRIVER_FAILURE")

    def test_explicit_native_finance_veto_is_distinct_from_generic_failure(self):
        self.assertEqual(native_post_outcome_class(
            {"driver_error": "org.postgresql.util.PSQLException: BAOBAB_NATIVE_FINANCE_DENIED"}
        ), "BAOBAB_NATIVE_FINANCE_DENIED")
        self.assertEqual(native_post_outcome_class(
            {"post_error": "BAOBAB_NATIVE_FINANCE_DENIED"}
        ), "BAOBAB_NATIVE_FINANCE_DENIED")
        self.assertNotEqual(native_post_outcome_class(
            {"driver_error": "timeout"}
        ), "BAOBAB_NATIVE_FINANCE_DENIED")

    def test_clean_posting_requires_absence_of_all_native_error_channels(self):
        self.assertTrue(native_post_clean({"post_error": "null"}))
        self.assertTrue(native_post_clean({"post_error": ""}))
        self.assertTrue(native_post_clean({}))
        self.assertFalse(native_post_clean(
            {"post_error": "null", "driver_error": "JVM exception"}
        ))

    def test_matchinv_conflicted_facts_never_trigger_unqualified_reposting(self):
        # The real witnessed S04b scenario remains required. This source
        # regression merely stops accidental removal of its immutable guard.
        source = (Path(__file__).resolve().parents[2] / "idempiere" / "acceptance"
                  / "erp-a" / "driver" / "gate_d_erp_a.py").read_text()
        self.assertIn(
            'match_status_before != "Y" and int(match_facts_before or "0") == 0',
            source,
        )
        self.assertIn("POSTING_STATE_CONFLICT_WITH_COMMITTED_FACTS", source)
        self.assertIn("forced_refused = native_post_outcome_class(forced) == DENIED", source)


if __name__ == "__main__":
    unittest.main()
