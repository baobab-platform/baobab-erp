"""Experimental PostgreSQL 17 BP-04 employment-proposal adapter, never a live HR API.

The caller MUST verify IAM/CP before invoking append. This adapter has no
independent grant and does not activate employment. Pass a live connection;
the caller owns commit/rollback, including any surrounding application work.
"""
from __future__ import annotations

import psycopg

from .model import EmploymentVersion, PeopleDomainError


class PostgresEmploymentProposalStore:
    def __init__(self, connection: psycopg.Connection):
        self._connection = connection

    def latest(self, *, tenant_id: str, employer_id: str, person_ref: str) -> EmploymentVersion | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT tenant_id, legal_employer_id, person_ref, version,
                          effective_from, effective_until, work_jurisdiction,
                          tax_jurisdiction, pay_currency, contract_evidence_ref, state
                     FROM baobab_people.employment_proposal
                    WHERE tenant_id = %s AND legal_employer_id = %s AND person_ref = %s
                    ORDER BY version DESC LIMIT 1""",
                (tenant_id, employer_id, person_ref),
            )
            row = cursor.fetchone()
        return EmploymentVersion(*row) if row else None

    def append_if_version(
        self, record: EmploymentVersion, *, previous_version: int | None,
        principal_ref: str,
    ) -> None:
        if not isinstance(principal_ref, str) or not principal_ref or any(c.isspace() for c in principal_ref):
            raise PeopleDomainError("Attested workforce principal required")
        # pg_advisory_xact_lock is transaction-owned and shared with P0001's
        # trigger. A caller cannot acquire the lock for a different employer
        # to bypass the version check; the database rechecks on INSERT.
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT pg_advisory_xact_lock(hashtextextended(
                     jsonb_build_array('people-employment', %s, %s, %s)::text, 0))""",
                (record.tenant_id, record.legal_employer_id, record.person_ref),
            )
            cursor.execute(
                """SELECT version, effective_from, effective_until
                     FROM baobab_people.employment_proposal
                    WHERE tenant_id = %s AND legal_employer_id = %s AND person_ref = %s
                    ORDER BY version DESC LIMIT 1""",
                (record.tenant_id, record.legal_employer_id, record.person_ref),
            )
            prior = cursor.fetchone()
            if (prior[0] if prior else None) != previous_version:
                raise PeopleDomainError("Concurrent employment version change")
            if (prior is None and record.version != 1) or (
                prior is not None and (
                    record.version != prior[0] + 1
                    or record.effective_from <= prior[1]
                    or (prior[2] is not None and record.effective_from < prior[2])
                )
            ):
                raise PeopleDomainError("Employment version must move forward")
            cursor.execute(
                """INSERT INTO baobab_people.employment_proposal
                    (tenant_id, legal_employer_id, person_ref, version, effective_from,
                     effective_until, work_jurisdiction, tax_jurisdiction, pay_currency,
                     contract_evidence_ref, writer_principal_ref, state)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    record.tenant_id, record.legal_employer_id, record.person_ref,
                    record.version, record.effective_from, record.effective_until,
                    record.work_jurisdiction, record.tax_jurisdiction, record.pay_currency,
                    record.contract_evidence_ref, principal_ref, record.state,
                ),
            )
