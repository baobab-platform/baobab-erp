"""Postgres-backed OutboxStore against baobab.event_outbox.

See db/migrations/0004_create_event_outbox.sql. `record()` deliberately does not
commit -- it must run inside the caller's own transaction so the outbox row and the
operational change it describes commit or roll back together (ADR-ERP-006). The
other methods are independent units of work run by the dispatcher and commit
themselves.
"""

import json
from dataclasses import dataclass
from datetime import datetime

import psycopg

from datetime import UTC

from events import registry
from events.cloudevent import CloudEvent, EnvelopeError
from events.envelope import EventEnvelope


@dataclass(frozen=True, slots=True)
class PostgresOutboxRecord:
    name: str
    attempts: int
    status: str
    event: CloudEvent
    created_at: datetime | None = None


class PostgresOutboxStore:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record(self, envelope: EventEnvelope) -> None:
        """Records a LEGACY-shaped domain event as 'held': it is kept, never delivered. Shared rejects the
        legacy envelope and no registered canonical event exists yet for these facts (see
        db/migrations/0013_event_cloudevents.sql). Must be called within the caller's own transaction."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.event_outbox
                    (event_id, event_type, schema_version, tenant_id, entity_id,
                     correlation_id, payload_json, occurred_at, status, last_error, envelope_format)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s, 'held',
                        'legacy envelope: no registered canonical event to deliver as', 'legacy')
                """,
                (
                    envelope.event_id,
                    envelope.event_type,
                    envelope.schema_version,
                    envelope.tenant_id,
                    envelope.entity_id,
                    envelope.correlation_id,
                    json.dumps(envelope.payload, separators=(",", ":"), sort_keys=True),
                    envelope.occurred_at,
                ),
            )

    def record_event(self, event: CloudEvent) -> None:
        """Records a canonical event for delivery. Refuses anything ERP does not produce. Must be called
        within the caller's own transaction; does not commit."""
        event.validate()
        if event.type not in registry.PRODUCED or event.source != registry.ERP_SOURCE:
            raise EnvelopeError(f"{event.type} from {event.source} is not an event baobab-erp produces")
        if event.dataschema != registry.dataschema_for(event.type):
            raise EnvelopeError("dataschema does not match the registered schema for the event type")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO baobab.event_outbox
                    (event_id, event_type, tenant_id, payload_json, occurred_at, envelope_format,
                     ce_source, ce_subject, ce_dataschema, ce_scope, ce_correlation_id, ce_causation_id,
                     ce_idempotency_key, ce_traceparent, ce_tracestate)
                VALUES (%s::uuid, %s, %s, %s::jsonb, %s, 'cloudevents',
                        %s, %s, %s, %s, %s::uuid, %s::uuid, %s, %s, %s)
                """,
                (
                    event.id, event.type, event.tenantid,
                    json.dumps(event.data, separators=(",", ":"), sort_keys=True), event.time,
                    event.source, event.subject, event.dataschema, event.baobabscope, event.correlationid,
                    event.causationid, event.idempotencykey, event.traceparent, event.tracestate,
                ),
            )

    def held_count(self) -> int:
        """Legacy-shaped events recorded but not deliverable."""
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM baobab.event_outbox WHERE status = 'held'")
            count = cursor.fetchone()[0]
        self._connection.commit()
        return count

    def pending(self, limit: int = 100, *, types: tuple[str, ...] | None = None,
                exclude_types: tuple[str, ...] | None = None) -> list[PostgresOutboxRecord]:
        """Canonical events due for delivery, oldest business time first: pending ones, and retries whose backoff has
        elapsed. Legacy 'held' rows are never returned. ``types`` restricts to those event types and ``exclude_types`` skips
        them, so each destination drains only what it is configured to carry."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, event_type, tenant_id, payload_json, occurred_at, attempts, status,
                       ce_source, ce_subject, ce_dataschema, ce_scope, ce_correlation_id, ce_causation_id,
                       ce_idempotency_key, ce_traceparent, ce_tracestate, created_at
                FROM baobab.event_outbox
                WHERE status IN ('pending', 'retry') AND envelope_format = 'cloudevents'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                  AND (%s::text[] IS NULL OR event_type = ANY(%s::text[]))
                  AND (%s::text[] IS NULL OR NOT (event_type = ANY(%s::text[])))
                ORDER BY occurred_at
                LIMIT %s
                """,
                (list(types) if types else None, list(types) if types else None,
                 list(exclude_types) if exclude_types else None, list(exclude_types) if exclude_types else None, limit),
            )
            rows = cursor.fetchall()
        self._connection.commit()

        records = []
        for (event_id, event_type, tenant_id, data, occurred_at, attempts, status, source, subject,
             dataschema, scope, correlation_id, causation_id, idempotency_key, traceparent, tracestate,
             created_at) in rows:
            event = CloudEvent(
                id=str(event_id), type=event_type, source=source, subject=subject,
                time=occurred_at.astimezone(UTC), dataschema=dataschema, baobabscope=scope,
                correlationid=str(correlation_id), data=data, tenantid=tenant_id,
                causationid=str(causation_id) if causation_id else None,
                idempotencykey=idempotency_key, traceparent=traceparent, tracestate=tracestate,
            ).validate()
            records.append(PostgresOutboxRecord(name=str(event_id), attempts=attempts, status=status, event=event,
                                                created_at=created_at))
        return records

    def mark_delivered(self, name: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "UPDATE baobab.event_outbox SET status = 'delivered', delivered_at = now(), next_attempt_at = NULL "
                "WHERE event_id = %s::uuid",
                (name,),
            )
        self._connection.commit()

    def mark_retry(self, name: str, attempts: int, error: str, delay_seconds: int = 0) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE baobab.event_outbox
                SET status = 'retry', attempts = %s, last_error = %s,
                    next_attempt_at = now() + make_interval(secs => %s)
                WHERE event_id = %s::uuid
                """,
                (attempts, error, delay_seconds, name),
            )
        self._connection.commit()

    def mark_dead_letter(self, name: str, attempts: int, error: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE baobab.event_outbox
                SET status = 'dead_letter', attempts = %s, last_error = %s, dead_lettered_at = now(),
                    next_attempt_at = NULL
                WHERE event_id = %s::uuid
                """,
                (attempts, error, name),
            )
        self._connection.commit()

    def stats(self, *, types: tuple[str, ...] | None = None, exclude_types: tuple[str, ...] | None = None) -> dict:
        """The delivery backlog of the selected canonical events: counts by state, how many are due now, and the age in
        seconds of the oldest undelivered one. Operators alert on dead_letter > 0 and a growing oldest_undelivered_seconds."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FILTER (WHERE status = 'pending'),
                       count(*) FILTER (WHERE status = 'retry'),
                       count(*) FILTER (WHERE status = 'dead_letter'),
                       count(*) FILTER (WHERE status = 'delivered'),
                       count(*) FILTER (WHERE status IN ('pending', 'retry')
                                         AND (next_attempt_at IS NULL OR next_attempt_at <= now())),
                       COALESCE(EXTRACT(EPOCH FROM now() - min(created_at) FILTER (WHERE status IN ('pending', 'retry'))), 0)
                  FROM baobab.event_outbox
                 WHERE envelope_format = 'cloudevents'
                   AND (%s::text[] IS NULL OR event_type = ANY(%s::text[]))
                   AND (%s::text[] IS NULL OR NOT (event_type = ANY(%s::text[])))
                """,
                (list(types) if types else None, list(types) if types else None,
                 list(exclude_types) if exclude_types else None, list(exclude_types) if exclude_types else None),
            )
            pending, retry, dead, delivered, due, oldest = cursor.fetchone()
        self._connection.commit()
        return {"pending": pending, "retry": retry, "dead_letter": dead, "delivered": delivered, "due": due,
                "oldest_undelivered_seconds": int(oldest)}
