"""Postgres store of Finance-approved financial configuration baselines (db/migrations/0014, ADR-ERP-008).

Append-only and versioned per legal entity. Like the other ERP stores it never commits: the caller owns the transaction.
The baseline types live in provisioning.finance_baseline, which needs no database driver."""
from __future__ import annotations

from datetime import date, datetime, timezone

import psycopg

from provisioning.finance_baseline import (
    BASELINE_ID_SQL,
    EFFECTIVE,
    NOT_YET_EFFECTIVE,
    SUPERSEDED,
    SYNTHETIC_APPROVERS,
    WITHDRAWN,
    FinanceBaselineError,
    FinanceBaselineSource,
    FinancialConfigurationBaseline,
)

__all__ = ["PostgresFinanceBaselineStore", "FinanceBaselineError", "FinanceBaselineSource",
           "FinancialConfigurationBaseline", "SYNTHETIC_APPROVERS"]

_COLUMNS = ("legal_entity_id, version, functional_currency, fiscal_year_start_month, chart_of_accounts_template, "
            "accounting_schema, tax_profile, costing_method, effective_from, approved_by, approved_at, evidence_reference")


def _text(value: str, name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned or cleaned.startswith("REQUIRED_"):
        raise FinanceBaselineError(f"{name} is missing or a placeholder")
    return cleaned


class PostgresFinanceBaselineStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record(
        self, *, legal_entity_id: str, functional_currency: str, fiscal_year_start_month: int,
        chart_of_accounts_template: str, accounting_schema: str, tax_profile: str, costing_method: str,
        effective_from: date, approved_by: str, approved_at: datetime, evidence_reference: str,
        now: datetime | None = None,
    ) -> FinancialConfigurationBaseline:
        """Record the next version of a legal entity's baseline. The approver must be a named person with evidence."""
        approver = _text(approved_by, "approved_by")
        if approver.lower() in SYNTHETIC_APPROVERS:
            raise FinanceBaselineError(f"approved_by {approver!r} is not an accountable person")
        if approved_at.tzinfo is None:
            raise FinanceBaselineError("approved_at has no time zone")
        if approved_at > (now or datetime.now(timezone.utc)):
            raise FinanceBaselineError("approved_at is in the future")
        entity = _text(legal_entity_id, "legal_entity_id")
        values = (
            entity, _text(functional_currency, "functional_currency"), int(fiscal_year_start_month),
            _text(chart_of_accounts_template, "chart_of_accounts_template"), _text(accounting_schema, "accounting_schema"),
            _text(tax_profile, "tax_profile"), _text(costing_method, "costing_method"), effective_from, approver,
            approved_at, _text(evidence_reference, "evidence_reference"))
        with self._connection.cursor() as cursor:
            # Serialise concurrent recordings for one legal entity so versions are dense and unique.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (entity,))
            cursor.execute(
                f"""INSERT INTO baobab.financial_configuration_baseline ({_COLUMNS})
                    SELECT %s, COALESCE(MAX(version), 0) + 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                      FROM baobab.financial_configuration_baseline WHERE legal_entity_id = %s
                    RETURNING {_COLUMNS}""",
                (values[0], *values[1:], entity))
            return _row(cursor.fetchone())

    def effective(self, legal_entity_id: str, on: date) -> FinancialConfigurationBaseline | None:
        """The baseline in force on a date: the latest effective_from not after it, then the highest version, among the
        versions whose approval had not been withdrawn by then. A withdrawal takes effect on the day it was recorded and does
        not rewrite earlier history. None if none."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"""SELECT {_COLUMNS} FROM baobab.financial_configuration_baseline b
                     WHERE legal_entity_id = %s AND effective_from <= %s
                       AND NOT EXISTS (SELECT 1 FROM baobab.financial_configuration_baseline_withdrawal w
                                        WHERE w.legal_entity_id = b.legal_entity_id AND w.version = b.version
                                          AND (w.withdrawn_at AT TIME ZONE 'UTC')::date <= %s)
                     ORDER BY effective_from DESC, version DESC LIMIT 1""", (legal_entity_id, on, on))
            row = cursor.fetchone()
        return _row(row) if row else None

    def get(self, legal_entity_id: str, version: int) -> FinancialConfigurationBaseline | None:
        """One exact approved version, whatever its standing (a withdrawn or superseded version is still returned)."""
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT {_COLUMNS} FROM baobab.financial_configuration_baseline "
                           "WHERE legal_entity_id = %s AND version = %s", (legal_entity_id, version))
            row = cursor.fetchone()
        return _row(row) if row else None

    def legal_entity_of(self, baseline_id: str) -> str | None:
        """The legal entity whose baselines carry this lineage id, or None. The id is derived from the legal entity, so this
        recomputes it rather than trusting a stored copy."""
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT DISTINCT legal_entity_id FROM baobab.financial_configuration_baseline "
                           f"WHERE {BASELINE_ID_SQL} = %s", (baseline_id,))
            row = cursor.fetchone()
        return row[0] if row else None

    def withdraw(self, *, legal_entity_id: str, version: int, withdrawn_by: str, withdrawn_at: datetime, reason: str,
                 evidence_reference: str, now: datetime | None = None) -> None:
        """Record that Finance withdrew its approval of one version. The approved version itself is never changed."""
        person = _text(withdrawn_by, "withdrawn_by")
        if person.lower() in SYNTHETIC_APPROVERS:
            raise FinanceBaselineError(f"withdrawn_by {person!r} is not an accountable person")
        if withdrawn_at.tzinfo is None:
            raise FinanceBaselineError("withdrawn_at has no time zone")
        if withdrawn_at > (now or datetime.now(timezone.utc)):
            raise FinanceBaselineError("withdrawn_at is in the future")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO baobab.financial_configuration_baseline_withdrawal
                   (legal_entity_id, version, withdrawn_by, withdrawn_at, reason, evidence_reference)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (_text(legal_entity_id, "legal_entity_id"), version, person, withdrawn_at, _text(reason, "reason"),
                 _text(evidence_reference, "evidence_reference")))

    def status(self, baseline: FinancialConfigurationBaseline, on: date) -> str:
        """The standing of one approved version on a date: WITHDRAWN if Finance had withdrawn it by then, NOT_YET_EFFECTIVE if it starts
        later, EFFECTIVE if it is the version in force, otherwise SUPERSEDED by the one that is."""
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM baobab.financial_configuration_baseline_withdrawal "
                           "WHERE legal_entity_id = %s AND version = %s AND (withdrawn_at AT TIME ZONE 'UTC')::date <= %s",
                           (baseline.legal_entity_id, baseline.version, on))
            if cursor.fetchone():
                return WITHDRAWN
        if baseline.effective_from > on:
            return NOT_YET_EFFECTIVE
        in_force = self.effective(baseline.legal_entity_id, on)
        return EFFECTIVE if in_force is not None and in_force.version == baseline.version else SUPERSEDED

    def history(self, legal_entity_id: str) -> list[FinancialConfigurationBaseline]:
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT {_COLUMNS} FROM baobab.financial_configuration_baseline "
                           "WHERE legal_entity_id = %s ORDER BY version", (legal_entity_id,))
            return [_row(row) for row in cursor.fetchall()]


def _row(row) -> FinancialConfigurationBaseline:
    return FinancialConfigurationBaseline(
        legal_entity_id=row[0], version=row[1], functional_currency=row[2], fiscal_year_start_month=row[3],
        chart_of_accounts_template=row[4], accounting_schema=row[5], tax_profile=row[6], costing_method=row[7],
        effective_from=row[8], approved_by=row[9], approved_at=row[10], evidence_reference=row[11])
