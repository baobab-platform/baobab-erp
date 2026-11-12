"""ERP-A native posting error classification cannot confuse OSGi failure with success.

The real acceptance gate still requires iDempiere/PostgreSQL readback. These
small tests protect its fail-closed interpretation of the file-driver protocol.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "idempiere" / "acceptance" / "erp-a" / "driver"))

from erpalib import native_post_clean, native_post_outcome_class  # noqa: E402


def test_native_jvm_driver_errors_are_not_successful_replays():
    for result in (
        {"driver_error": "java.lang.IllegalArgumentException: unsupported native posting source"},
        {"driver_error": "timeout"},
        {"driver_error": "java.lang.RuntimeException"},
        {"error": "SQL operation failed"},
        {"post_error": "posting returned an error"},
    ):
        assert not native_post_clean(result)
    assert native_post_outcome_class(
        {"driver_error": "java.lang.IllegalArgumentException: unsupported native posting source"}
    ) == "UNSUPPORTED_NATIVE_POSTING_SOURCE"
    assert native_post_outcome_class({"driver_error": "timeout"}) == "NATIVE_DRIVER_FAILURE"


def test_explicit_native_finance_veto_is_distinct_from_generic_failure():
    assert native_post_outcome_class(
        {"driver_error": "org.postgresql.util.PSQLException: BAOBAB_NATIVE_FINANCE_DENIED"}
    ) == "BAOBAB_NATIVE_FINANCE_DENIED"
    assert native_post_outcome_class(
        {"post_error": "BAOBAB_NATIVE_FINANCE_DENIED"}
    ) == "BAOBAB_NATIVE_FINANCE_DENIED"
    assert native_post_outcome_class({"driver_error": "timeout"}) != "BAOBAB_NATIVE_FINANCE_DENIED"


def test_clean_posting_requires_absence_of_all_native_error_channels():
    assert native_post_clean({"post_error": "null"})
    assert native_post_clean({"post_error": ""})
    assert native_post_clean({})
    assert not native_post_clean({"post_error": "null", "driver_error": "JVM exception"})


def test_matchinv_conflicted_facts_never_trigger_unqualified_reposting():
    source = (Path(__file__).resolve().parents[2] / "idempiere" / "acceptance"
              / "erp-a" / "driver" / "gate_d_erp_a.py").read_text()
    assert 'match_status_before != "Y" and int(match_facts_before or "0") == 0' in source
    assert "POSTING_STATE_CONFLICT_WITH_COMMITTED_FACTS" in source
    assert "forced_refused = native_post_outcome_class(forced) == DENIED" in source
