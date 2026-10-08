"""Postgres persistence of document accounting revisions (db/migrations/0022). Caller owns the transaction."""
from __future__ import annotations

import json
from datetime import datetime

from order_to_cash.accounting_outcomes import RANK, Advanced


class PostgresDocumentOutcomeStore:
    def __init__(self, connection):
        self._connection = connection

    def advance(self, *, tenant_id: str, document_type: str, document_id: str, status: str, detail: dict,
                now: datetime) -> Advanced:
        """Revision 1 on first sight; +1 only when the status or detail differs from the stored revision. Row-locked, so two
        concurrent requests for one document cannot both claim the same revision."""
        key = (tenant_id, document_type, document_id)
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT revision, status, detail, first_seen_at FROM baobab.document_outcome "
                "WHERE tenant_id=%s AND document_type=%s AND document_id=%s FOR UPDATE", key)
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO baobab.document_outcome (tenant_id, document_type, document_id, revision, status, detail, "
                    "first_seen_at, updated_at) VALUES (%s,%s,%s,1,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING",
                    (*key, status, json.dumps(detail, sort_keys=True), now, now))
                if cursor.rowcount == 1:
                    return Advanced(1, now, True)
                cursor.execute(
                    "SELECT revision, status, detail, first_seen_at FROM baobab.document_outcome "
                    "WHERE tenant_id=%s AND document_type=%s AND document_id=%s FOR UPDATE", key)
                row = cursor.fetchone()
            revision, stored_status, stored_detail, first_seen = row
            if isinstance(stored_detail, str):
                stored_detail = json.loads(stored_detail)
            if RANK.get(status, 0) < RANK.get(stored_status, 0):  # statuses only move forward
                return Advanced(int(revision), first_seen, False)
            if stored_status == status and stored_detail == detail:
                return Advanced(int(revision), first_seen, False)
            cursor.execute(
                "UPDATE baobab.document_outcome SET revision=revision+1, status=%s, detail=%s::jsonb, updated_at=%s "
                "WHERE tenant_id=%s AND document_type=%s AND document_id=%s",
                (status, json.dumps(detail, sort_keys=True), now, *key))
            return Advanced(int(revision) + 1, first_seen, True)
