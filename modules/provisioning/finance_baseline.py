"""A Finance-approved financial configuration baseline (ADR-ERP-008) and the source that resolves one.

Database-free on purpose: the provisioning domain and its unit tests depend on these types, and only the Postgres store
(finance_baseline_store) needs a driver. Nothing here defaults or infers a value; a baseline exists only as recorded,
with a named approver and evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
