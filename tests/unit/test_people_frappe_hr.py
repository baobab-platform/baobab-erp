"""Frappe HR real REST API adapter contract tests; no employee or salary data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlparse
import unittest

from people.providers.frappe_hr import (
    FrappeHRPayrollRunReader, FrappePayrollEntryStatus,
)
from people.providers.selection import ProviderSelection, ProviderSelectionDenied


NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


class CurrentCP:
    def __init__(self):
        self.calls = 0
        self.error = None
        self.provider = "provider_registered1"
        self.employer = "EXACT-EMPLOYER"

    def resolve(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        assert kwargs["capability_key"] == "payroll.run.read"
        assert kwargs["tenant_id"] == "tn_test1"
        assert kwargs["legal_employer_id"] == "EXACT-EMPLOYER"
        return ProviderSelection(
            "tn_test1", self.employer, "ZA", "payroll.run.read",
            "bind_exact1", self.provider, 4, "EXTERNAL",
            "qualified_receipt1", NOW, NOW + timedelta(seconds=22),
        )


class ProviderTransport:
    def __init__(self):
        self.result = {"data": [{
            "name": "PAYROLL-2026-001", "company": "Acme ZA Ltd",
            "docstatus": 1, "modified": "2026-11-12 08:59:59.000000",
        }]}
        self.calls = []

    def __call__(self, url, auth):
        self.calls.append((url, auth))
        return json.dumps(self.result).encode()


class FrappeHRAdapterTests(unittest.TestCase):
    def setUp(self):
        self.cp = CurrentCP()
        self.source = ProviderTransport()
        self.adapter = FrappeHRPayrollRunReader(
            selector=self.cp, context_id="ctx_exact", correlation_id="12345678-1234-4234-8234-123456789012",
            tenant_id="tn_test1", legal_employer_id="EXACT-EMPLOYER", jurisdiction="ZA",
            provider_id="provider_registered1", endpoint="https://hr.example.test",
            company="Acme ZA Ltd", api_key="aaaaaaaa", api_secret="bbbbbbbb",
            transport=self.source,
        )

    def test_live_source_reads_only_metadata_and_uses_current_cp_selection(self):
        result = self.adapter.read_status(source_run_ref="PAYROLL-2026-001", now=NOW)
        self.assertIsInstance(result, FrappePayrollEntryStatus)
        self.assertEqual(result.source_status, "SUBMITTED")
        self.assertEqual(result.binding_revision, 4)
        self.assertEqual(self.cp.calls, 1)
        self.assertNotIn("qualified", str(result).lower())
        url, auth = self.source.calls[0]
        self.assertEqual(auth, "token aaaaaaaa:bbbbbbbb")
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.path, "/api/resource/Payroll%20Entry")
        query = parse_qs(parsed.query)
        self.assertEqual(json.loads(query["fields"][0]),
                         ["name", "company", "docstatus", "modified"])
        self.assertEqual(json.loads(query["filters"][0]),
                         [["name", "=", "PAYROLL-2026-001"], ["company", "=", "Acme ZA Ltd"]])
        for prohibited in ("Employee", "Salary Slip", "bank", "salary", "earnings", "tax_id"):
            self.assertNotIn(prohibited, url)

    def test_denies_wrong_selected_provider_before_any_external_http(self):
        for drift in ("provider", "employer"):
            with self.subTest(drift=drift):
                setattr(self.cp, drift, "provider_neighbor" if drift == "provider" else "OTHER-EMPLOYER")
                with self.assertRaises(ProviderSelectionDenied):
                    self.adapter.read_status(source_run_ref="PAYROLL-2026-001", now=NOW)
                self.assertEqual(self.source.calls, [])
                setattr(self.cp, drift, "provider_registered1" if drift == "provider" else "EXACT-EMPLOYER")

    def test_denies_revoked_cp_or_context_before_external_http(self):
        self.cp.error = ProviderSelectionDenied("revoked")
        with self.assertRaises(ProviderSelectionDenied):
            self.adapter.read_status(source_run_ref="PAYROLL-2026-001", now=NOW)
        self.assertEqual(self.source.calls, [])

    def test_denies_missing_duplicated_foreign_or_expanded_records(self):
        cases = {
            "missing": {"data": []},
            "ambiguous": {"data": [self.source.result["data"][0]] * 2},
            "foreign_company": {"data": [{**self.source.result["data"][0], "company": "Other Company"}]},
            "foreign_ref": {"data": [{**self.source.result["data"][0], "name": "OTHER-2026"}]},
            "extra_pii": {"data": [{**self.source.result["data"][0], "salary": 1}]},
            "wrong_state": {"data": [{**self.source.result["data"][0], "docstatus": 3}]},
            "fabricated_boolean": {"data": [{**self.source.result["data"][0], "docstatus": True}]},
            "malformed_timestamp": {"data": [{**self.source.result["data"][0], "modified": "today"}]},
            "provider_errors": {"exc_type": "permission_error"},
        }
        for label, result in cases.items():
            with self.subTest(case=label):
                self.source.calls.clear()
                self.source.result = result
                with self.assertRaises(ProviderSelectionDenied):
                    self.adapter.read_status(source_run_ref="PAYROLL-2026-001", now=NOW)

    def test_no_client_supplied_external_ref_injection_or_http_fallback(self):
        for ref in ("../../Employee", "PAYROLL-1?fields=*", " Employee ", "", "PAYROLL-2026-001#frag"):
            with self.subTest(ref=ref):
                with self.assertRaises(ProviderSelectionDenied):
                    self.adapter.read_status(source_run_ref=ref, now=NOW)
                self.assertEqual(self.source.calls, [])
        with self.assertRaises(ProviderSelectionDenied):
            FrappeHRPayrollRunReader(
                selector=self.cp, context_id="ctx", correlation_id="corr",
                tenant_id="tn_test1", legal_employer_id="EXACT-EMPLOYER", jurisdiction="ZA",
                provider_id="provider_registered1", endpoint="http://hr.example.test",
                company="Acme ZA Ltd", api_key="aaaaaaaa", api_secret="bbbbbbbb",
            )


if __name__ == "__main__":
    unittest.main()
