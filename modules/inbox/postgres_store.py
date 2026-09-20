"""Postgres-backed InboxStore against baobab.event_inbox.

See db/migrations/0005_create_event_inbox.sql. Each method commits its own
transaction: inbox receipt is an independent unit of work, not part of a larger
business transaction the caller controls.
"""

import psycopg

from events.envelope import EventEnvelope


class PostgresInboxStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def exists(self, event_id: str) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM baobab.event_inbox WHERE event_id = %s::uuid",
                (event_id,),
            )
            found = cursor.fetchone() is not None
        self._connection.commit()
        return found

    def record_received(self, envelope: EventEnvelope, payload_json: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.event_inbox
                    (event_id, event_type, schema_version, source_engine, correlation_id,
                     tenant_id, entity_id, payload_json)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    envelope.event_id,
                    envelope.event_type,
                    envelope.schema_version,
                    envelope.source,
                    envelope.correlation_id,
                    envelope.tenant_id,
                    envelope.entity_id,
                    payload_json,
                ),
            )
        self._connection.commit()

    def mark_processed(self, event_id: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE baobab.event_inbox
                   SET status = 'processed', processed_at = now(), last_error = NULL
                 WHERE event_id = %s::uuid
                """,
                (event_id,),
            )
        self._connection.commit()

    def mark_failed(self, event_id: str, error: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE baobab.event_inbox
                   SET status = 'failed', last_error = %s
                 WHERE event_id = %s::uuid
                """,
                (error[:2000], event_id),
            )
        self._connection.commit()
