"""Frappe HR v15+ real REST adapter for CP-selected payroll.run.read.

Reads **only** one vendor Payroll Entry's opaque name, company, modified
timestamp and docstatus. It never reads Salary Slip/Employee, performs a
payroll calculation, publishes a canonical signed receipt or claims statutory
qualification. Employer-specific credential and company binding are provided
from the operator's external secret/custody store, never inferred from OAuth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import ssl
import unicodedata
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError, URLError

from .selection import (
    CPProviderSelector, ProviderSelection, ProviderSelectionDenied,
    _NoRedirect, _endpoint, _unique_json,
)


def frappe_read_https(url: str, auth_header: str) -> bytes:
    """Real Frappe v1 REST GET, TLS-verified, no proxies or redirects."""
    if not url.startswith("https://") or len(url) > 2048:
        raise ProviderSelectionDenied("Frappe endpoint denied")
    if (not auth_header.startswith("token ") or len(auth_header) > 400
            or any(c.isspace() for c in auth_header[6:])):
        raise ProviderSelectionDenied("Frappe employer credential unavailable")
    request = Request(url, headers={
        "Authorization": auth_header, "Accept": "application/json",
    }, method="GET")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())
    try:
        with opener.open(request, timeout=7) as response:
            if response.status != 200 or response.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ProviderSelectionDenied("Frappe status response denied")
            body = response.read(8193)
    except (HTTPError, URLError, OSError, TimeoutError) as err:
        raise ProviderSelectionDenied("Frappe source unavailable or refused access") from err
    if len(body) > 8192:
        raise ProviderSelectionDenied("Frappe response exceeds metadata-only budget")
    return body


@dataclass(frozen=True, slots=True)
class FrappePayrollEntryStatus:
    """Vendor status observation, never VerifiedCalculation or payroll approval."""
    tenant_id: str
    legal_employer_id: str
    jurisdiction: str
    provider_id: str
    binding_id: str
    binding_revision: int
    source_run_ref: str
    source_company: str
    source_docstatus: int
    source_modified: str
    observed_at: datetime

    @property
    def source_status(self) -> str:
        return {0: "DRAFT", 1: "SUBMITTED", 2: "CANCELLED"}[self.source_docstatus]


@dataclass(frozen=True, slots=True)
class FrappeHRPayrollRunReader:
    """Read one tenant/employer-bound Payroll Entry from actual Frappe REST.

    Selection is re-read from CP on every call, including after credential
    rotation or source cancellation. An opaque external source_run_ref is
    pre-bound by the employer's adapter registry; never search by employee.
    """
    selector: CPProviderSelector
    context_id: str
    correlation_id: str
    tenant_id: str
    legal_employer_id: str
    jurisdiction: str
    provider_id: str
    # Operator's immutable registry entry for this exact provider/binding and
    # payroll run. A tenant-supplied run name must never select an arbitrary
    # Payroll Entry from the same employer's Frappe account.
    binding_id: str
    binding_revision: int
    registered_source_run_ref: str
    endpoint: str
    company: str
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    transport: Callable[[str, str], bytes] = field(default=frappe_read_https, repr=False)

    def __post_init__(self) -> None:
        _endpoint(self.endpoint, "")
        if (not isinstance(self.binding_id, str)
                or not re.fullmatch(r"bind_[a-z0-9]+", self.binding_id)
                or type(self.binding_revision) is not int or self.binding_revision < 1
                or not isinstance(self.registered_source_run_ref, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{2,119}", self.registered_source_run_ref)
                or not isinstance(self.company, str)
                or not self.company or len(self.company) > 120
                or self.company != self.company.strip()
                # Frappe company names may contain Unicode, commas and
                # punctuation. JSON+urlencode makes these filter values,
                # never executable URL/JSON syntax. Refuse control/format
                # characters without imposing an English-only character set.
                or any(unicodedata.category(ch).startswith("C") for ch in self.company)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", self.api_key)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", self.api_secret)):
            raise ProviderSelectionDenied("Employer-scoped Frappe credential configuration required")

    def read_status(self, *, source_run_ref: str, now: datetime) -> FrappePayrollEntryStatus:
        if (not isinstance(now, datetime) or now.tzinfo is None
                or not isinstance(source_run_ref, str)
                or source_run_ref != self.registered_source_run_ref):
            # A source reference is not caller-selectable. The employer's
            # trusted adapter registry must bind the exact run and credentials
            # before constructing this instance.
            raise ProviderSelectionDenied("Invalid employer-owned payroll source reference")
        now = now.astimezone(timezone.utc)
        selected = self.selector.resolve(
            context_id=self.context_id, correlation_id=self.correlation_id,
            capability_key="payroll.run.read", tenant_id=self.tenant_id,
            legal_employer_id=self.legal_employer_id,
            jurisdiction=self.jurisdiction, now=now,
        )
        if (not isinstance(selected, ProviderSelection)
                or selected.source_of_record != "EXTERNAL" or selected.provider_id != self.provider_id
                or selected.binding_id != self.binding_id
                or selected.binding_revision != self.binding_revision
                or selected.tenant_id != self.tenant_id
                or selected.legal_employer_id != self.legal_employer_id
                or selected.jurisdiction != self.jurisdiction or selected.expires_at <= now):
            raise ProviderSelectionDenied("Current CP-selected Frappe provider unavailable")
        # Frappe v1 resource API is documented to support filters and fields.
        # Return no Employee/Salary Slip/monetary data. Refuse duplicate source
        # records instead of picking an arbitrary first entry.
        query = urlencode({
            "fields": json.dumps(["name", "company", "docstatus", "modified"], separators=(",", ":")),
            "filters": json.dumps([["name", "=", source_run_ref], ["company", "=", self.company]], separators=(",", ":")),
            "limit_page_length": "2",
        })
        url = _endpoint(self.endpoint, "/api/resource/Payroll%20Entry") + "?" + query
        response = _unique_json(self.transport(url, "token " + self.api_key + ":" + self.api_secret), maximum=8192)
        if set(response) != {"data"} or not isinstance(response["data"], list) or len(response["data"]) != 1:
            raise ProviderSelectionDenied("Frappe payroll entry missing or ambiguous")
        item = response["data"][0]
        if (not isinstance(item, dict) or set(item) != {"name", "company", "docstatus", "modified"}
                or item["name"] != source_run_ref or item["company"] != self.company
                or type(item["docstatus"]) is not int or item["docstatus"] not in (0, 1, 2)
                or not isinstance(item["modified"], str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", item["modified"])):
            raise ProviderSelectionDenied("Frappe payroll result failed employer/source provenance")
        return FrappePayrollEntryStatus(
            tenant_id=self.tenant_id, legal_employer_id=self.legal_employer_id,
            jurisdiction=self.jurisdiction, provider_id=selected.provider_id,
            binding_id=selected.binding_id, binding_revision=selected.binding_revision,
            source_run_ref=source_run_ref, source_company=self.company,
            source_docstatus=item["docstatus"], source_modified=item["modified"],
            observed_at=now,
        )
