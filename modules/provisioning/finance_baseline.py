"""A Finance-approved financial configuration baseline (ADR-ERP-008) and the source that resolves one.

Database-free on purpose: the provisioning domain and its unit tests depend on these types, and only the Postgres store
(finance_baseline_store) needs a driver. Nothing here defaults or infers a value; a baseline exists only as recorded,
with a named approver and evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

# Actors that are not accountable people. The table refuses the same names; checking here reports it before the write.
SYNTHETIC_APPROVERS = frozenset({"system", "service", "bootstrap", "automation", "auto", "unknown", "n/a", "none"})


class FinanceBaselineError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FinancialConfigurationBaseline:
    legal_entity_id: str
    version: int
    functional_currency: str
    fiscal_year_start_month: int
    chart_of_accounts_template: str
    accounting_schema: str
    tax_profile: str
    costing_method: str
    effective_from: date
    approved_by: str
    approved_at: datetime
    evidence_reference: str


class FinanceBaselineSource(Protocol):
    def effective(self, legal_entity_id: str, on: date) -> FinancialConfigurationBaseline | None: ...


# --- Finance baseline reference and resolution (Shared erp/v1 1.3.0, finance-baseline.schema.json) -----------------------
#
# The Control Plane REFERS to an approved baseline version; the accounting configuration stays here. A reference names
# (baseline_id, version, digest): the id is a stable lineage per legal entity, the version is immutable approved content and
# the digest is a hash of exactly that content, so a provisioning consumes the approved version and never "whatever finance
# configuration ERP holds now".
import hashlib
import json
import re

BASELINE_ID = re.compile(r"^fb_[a-z0-9]+$")
BASELINE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
AUTHORITY = {"engine_id": "baobab-erp", "system_of_record": "FINANCE_BASELINE"}
EFFECTIVE, NOT_YET_EFFECTIVE, SUPERSEDED, WITHDRAWN = "EFFECTIVE", "NOT_YET_EFFECTIVE", "SUPERSEDED", "WITHDRAWN"

# The SQL form of baseline_id_for, so a baseline_id can be found without a second table; the two are pinned together by a test.
BASELINE_ID_SQL = "('fb_' || substr(encode(sha256(convert_to(legal_entity_id, 'UTF8')), 'hex'), 1, 32))"


def baseline_id_for(legal_entity_id: str) -> str:
    """The ERP-minted, stable lineage id of a legal entity's baselines (every version shares it)."""
    return "fb_" + hashlib.sha256(legal_entity_id.encode("utf-8")).hexdigest()[:32]


def baseline_digest(baseline: FinancialConfigurationBaseline) -> str:
    """SHA-256 of the canonical (RFC 8785) JSON of the approved version as stored, including the facts of its approval.

    Every member is a string or an integer, so JCS reduces to sorted keys, no whitespace and minimal escaping. The same
    approved version always has the same digest; a change to an approved baseline is a new version."""
    canonical = {
        "legal_entity_id": baseline.legal_entity_id, "version": baseline.version,
        "functional_currency": baseline.functional_currency, "fiscal_year_start_month": baseline.fiscal_year_start_month,
        "chart_of_accounts_template": baseline.chart_of_accounts_template, "accounting_schema": baseline.accounting_schema,
        "tax_profile": baseline.tax_profile, "costing_method": baseline.costing_method,
        "effective_from": baseline.effective_from.isoformat(), "approved_by": baseline.approved_by,
        "approved_at": baseline.approved_at.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "evidence_reference": baseline.evidence_reference,
    }
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def reference_of(baseline: FinancialConfigurationBaseline) -> dict:
    """The contract FinanceBaselineReference of an approved version. It carries no accounting value."""
    return {"baseline_id": baseline_id_for(baseline.legal_entity_id), "legal_entity_id": baseline.legal_entity_id,
            "version": baseline.version, "digest": baseline_digest(baseline),
            "effective_from": baseline.effective_from.isoformat(), "authority": dict(AUTHORITY)}


def resolution_of(baseline: FinancialConfigurationBaseline, status: str, now: datetime) -> dict:
    """The contract FinanceBaselineResolution: the reference, its current standing, and the one accounting value disclosed."""
    return {"reference": reference_of(baseline), "status": status, "functional_currency": baseline.functional_currency,
            "resolved_at": now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
