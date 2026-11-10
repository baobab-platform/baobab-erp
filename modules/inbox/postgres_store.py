"""Postgres-backed InboxStore against baobab.event_inbox.

See db/migrations/0005_create_event_inbox.sql and 0013_event_cloudevents.sql. Each method commits its own
transaction: inbox receipt is an independent unit of work, not part of a larger business transaction the
caller controls. Canonical events are deduplicated by (source, id).
"""

import psycopg

from events.cloudevent import CloudEvent


class PostgresInboxStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def exists(self, source: str, event_id: str) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM baobab.event_inbox
                WHERE envelope_format = 'cloudevents' AND ce_source = %s AND event_id = %s::uuid
                """,
                (source, event_id),
            )
            found = cursor.fetchone() is not None
        self._connection.commit()
        return found

    def record_received(self, event: CloudEvent, data_json: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.event_inbox
                    (event_id, event_type, tenant_id, payload_json, envelope_format,
                     ce_source, ce_subject, ce_dataschema, ce_scope, ce_correlation_id, ce_causation_id,
                     ce_idempotency_key, ce_traceparent, ce_tracestate, ce_time)
                VALUES (%s::uuid, %s, %s, %s::jsonb, 'cloudevents',
                        %s, %s, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s)
                ON CONFLICT (ce_source, event_id) WHERE envelope_format = 'cloudevents' DO NOTHING
                """,
                (
                    event.id, event.type, event.tenantid, data_json,
                    event.source, event.subject, event.dataschema, event.baobabscope, event.correlationid,
                    event.causationid, event.idempotencykey, event.traceparent, event.tracestate, event.time,
                ),
            )
        self._connection.commit()

    def assert_semantic_duplicate(self, event: CloudEvent) -> None:
        """Reject same (source,id) with changed business identity/payload.

        W3C traceparent and tracestate are deliberately diagnostic only and
        can change across legitimate redelivery. All immutable business facts,
        original event time and declared producer MUST remain identical.
        This read also resolves a concurrent INSERT ON CONFLICT DO NOTHING.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_type, tenant_id, payload_json, ce_subject,
                       ce_dataschema, ce_scope, ce_correlation_id::text,
                       ce_causation_id::text, ce_idempotency_key, ce_time
                  FROM baobab.event_inbox
                 WHERE envelope_format = 'cloudevents'
                   AND ce_source = %s AND event_id = %s::uuid
                """,
                (event.source, event.id),
            )
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            raise ValueError("ERP_EVENT_RECEIPT_NOT_PERSISTED")
        same = (
            row[0] == event.type and row[1] == event.tenantid and
            row[2] == event.data and row[3] == event.subject and
            row[4] == event.dataschema and row[5] == event.baobabscope and
            row[6] == event.correlationid and row[7] == event.causationid and
            row[8] == event.idempotencykey and row[9] == event.time
        )
        if not same:
            raise ValueError("ERP_EVENT_IDEMPOTENCY_CONFLICT")
