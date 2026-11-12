"""PostgreSQL 17 BP-04 draft-only metadata: no payroll, GL or payment execution."""
from __future__ import annotations

import psycopg

from .model import PayrollDraft, PayrollPolicyError


class PostgresPayrollDraftStore:
    def __init__(self, connection: psycopg.Connection):
        self._connection = connection

    def latest(self, *, tenant_id: str, employer_id: str, run_ref: str) -> PayrollDraft | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT run_ref, version, tenant_id, legal_employer_id, maker_ref,
                          period_from, period_until, statutory_jurisdiction,
                          currency, rule_pack_sha256, correction_of_run_ref
                     FROM baobab_people.payroll_draft
                    WHERE tenant_id = %s AND legal_employer_id = %s AND run_ref = %s
                    ORDER BY version DESC LIMIT 1""",
                (tenant_id, employer_id, run_ref),
            )
            row = cursor.fetchone()
        return PayrollDraft(*row) if row else None

    def append_if_version(self, draft: PayrollDraft, *, previous_version: int | None) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT pg_advisory_xact_lock(hashtextextended(
                     jsonb_build_array('people-draft', %s::text, %s::text, %s::text)::text, 0))""",
                (draft.tenant_id, draft.legal_employer_id, draft.run_ref),
            )
            cursor.execute(
                """SELECT version, period_from, period_until, statutory_jurisdiction,
                          currency, correction_of_run_ref
                     FROM baobab_people.payroll_draft
                    WHERE tenant_id = %s AND legal_employer_id = %s AND run_ref = %s
                    ORDER BY version DESC LIMIT 1""",
                (draft.tenant_id, draft.legal_employer_id, draft.run_ref),
            )
            prior = cursor.fetchone()
            if (prior[0] if prior else None) != previous_version:
                raise PayrollPolicyError("Concurrent payroll draft version change")
            if (prior is None and draft.version != 1) or (
                prior is not None and (
                    draft.version != prior[0] + 1
                    or (draft.period_from, draft.period_until, draft.statutory_jurisdiction,
                        draft.currency, draft.correction_of_run_ref) != prior[1:]
                )
            ):
                raise PayrollPolicyError("Payroll draft cannot change period or scope")
            cursor.execute(
                """INSERT INTO baobab_people.payroll_draft
                    (tenant_id,legal_employer_id,run_ref,version,maker_ref,period_from,
                     period_until,statutory_jurisdiction,currency,rule_pack_sha256,
                     correction_of_run_ref)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    draft.tenant_id, draft.legal_employer_id, draft.run_ref, draft.version,
                    draft.maker_ref, draft.period_from, draft.period_until,
                    draft.statutory_jurisdiction, draft.currency, draft.rule_pack_sha256,
                    draft.correction_of_run_ref,
                ),
            )
