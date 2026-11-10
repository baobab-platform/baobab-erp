"""Native RabbitMQ -> verified canonical CloudEvent -> durable ERP PostgreSQL inbox.

The durable receiver is deliberately NOT the financial business executor.
ACK means the signed event has been durably *admitted* in ERP's existing inbox;
the separately owned inbox_worker checks current native IAM/CP authority and
iDempiere consequences. No unauthorised event may be marked business-applied.

Topology (durable topic/queue, quorum, DLX, bindings) is provisioned by
Infrastructure; this consumer declares its queue *passively* and refuses to
silently create an ungoverned queue. No broker credentials or event payloads
are written to stdout, span attributes, or exception messages.
"""
from __future__ import annotations

import logging
import os
import signal
from urllib.parse import urlsplit

import pika
import psycopg

from application.observability import configure, consumer_span, diagnostic_outcome, shutdown
from inbox.postgres_store import PostgresInboxStore
from inbox.service import InvalidSignatureError, receive

EVENT_CONTENT_TYPE = "application/cloudevents+json"
EVENT_SIGNATURE_HEADER = "x-baobab-signature"
EXPECTED_QUEUE = "baobab.erp.trade-order.v1"
MAX_EVENT_BYTES = 1024 * 1024

logger = logging.getLogger("baobab.erp.amqp")
logger.setLevel(logging.INFO)


class RejectedEvent(ValueError):
    """Message is untrusted/invalid; broker DLX owns its poison evidence."""


def validate_connection_url(url: str, environment: str):
    parts = urlsplit(url)
    if parts.scheme not in ("amqp", "amqps") or not parts.hostname or not parts.username or not parts.password:
        raise RuntimeError("ERP_AMQP_CONNECTION_INVALID")
    if parts.scheme == "amqp" and environment not in ("development", "test", "integration"):
        raise RuntimeError("ERP_AMQP_TLS_REQUIRED")
    if parts.fragment:
        raise RuntimeError("ERP_AMQP_CONNECTION_INVALID")
    return url


def admit(body: bytes, signature: object, content_type: object, store, secret: str):
    """Verify authenticity *before* using remote trace context; commit inbox first."""
    if not isinstance(body, bytes) or len(body) == 0 or len(body) > MAX_EVENT_BYTES:
        raise RejectedEvent("ERP_EVENT_SIZE_INVALID")
    if content_type != EVENT_CONTENT_TYPE:
        raise RejectedEvent("ERP_EVENT_CONTENT_TYPE_INVALID")
    if not isinstance(signature, str) or not signature.startswith("sha256="):
        raise RejectedEvent("ERP_EVENT_SIGNATURE_MISSING")
    try:
        event = receive(body, signature, secret, store)
    except (InvalidSignatureError, ValueError, TypeError) as error:
        raise RejectedEvent("ERP_CANONICAL_EVENT_DENIED") from None

    # Event trace metadata is now authenticated by the signed canonical
    # envelope. A linked consumer span does not create an authority grant.
    with consumer_span(event.traceparent, "baobab.erp.inbox.admit") as span:
        span.set_attribute("messaging.message.id", str(event.id))
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.operation.type", "receive")
        diagnostic_outcome(span, "ADMITTED")
    return event


def delivery_callback(channel, method, properties, body, *, store_factory, secret,
                      after_commit_hook=None):
    """ACK after committed admission, reject poison, preserve transient failures."""
    tag = method.delivery_tag
    try:
        signature = (properties.headers or {}).get(EVENT_SIGNATURE_HEADER)
        with store_factory() as store:
            admit(body, signature, properties.content_type, store, secret)
        # Test-only injection lives in the disposable caller, not in the
        # shipped consumer. A process crash here proves broker redelivery
        # after the ERP PostgreSQL receipt committed but before ACK.
        if after_commit_hook is not None:
            after_commit_hook()
    except RejectedEvent:
        # The queue MUST have a pre-provisioned DLX; never requeue poison
        # endlessly or fabricate an ACCEPTED/PROCESSED receipt.
        channel.basic_reject(delivery_tag=tag, requeue=False)
        logger.warning("ERP_AMQP_EVENT_REJECTED")
    except Exception:
        # PostgreSQL unavailable/unknown: no success receipt and no ACK.
        # A real quorum queue retains the message for subsequent redelivery.
        channel.basic_nack(delivery_tag=tag, requeue=True)
        channel.stop_consuming()
        logger.error("ERP_AMQP_TRANSIENT_ADMISSION_FAILURE")
        raise RuntimeError("ERP_AMQP_ADMISSION_BLOCKED") from None
    else:
        channel.basic_ack(delivery_tag=tag)
        logger.info("ERP_AMQP_EVENT_DURABLY_ADMITTED")


class _PgStoreContext:
    def __init__(self, url: str):
        self.url = url
        self.connection = None

    def __enter__(self):
        self.connection = psycopg.connect(self.url)
        return PostgresInboxStore(self.connection)

    def __exit__(self, typ, value, tb):
        if self.connection is not None:
            self.connection.close()


def main():
    environment = os.environ.get("BAOBAB_ENVIRONMENT", "")
    if environment not in ("development", "test", "integration", "staging", "production"):
        raise RuntimeError("ERP_ENVIRONMENT_EXPLICITLY_REQUIRED")
    url = validate_connection_url(os.environ.get("BAOBAB_RABBITMQ_URL", ""), environment)
    database_url = os.environ.get("DATABASE_URL")
    secret = os.environ.get("BAOBAB_EVENT_SIGNING_SECRET")
    if not database_url or not secret or len(secret) < 24:
        raise RuntimeError("ERP_AMQP_DATABASE_AND_SIGNING_KEYS_REQUIRED")
    queue = os.environ.get("BAOBAB_AMQP_INBOX_QUEUE", EXPECTED_QUEUE)
    if queue != EXPECTED_QUEUE:
        raise RuntimeError("ERP_AMQP_GOVERNED_QUEUE_REQUIRED")
    configure()
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        channel = connection.channel()
        # An absent queue or inconsistent durable/DLX policy MUST block
        # startup rather than silently provision a second transport profile.
        channel.queue_declare(queue=queue, passive=True)
        channel.basic_qos(prefetch_count=10)
        channel.basic_consume(
            queue=queue,
            on_message_callback=lambda ch, method, properties, body:
                delivery_callback(
                    ch, method, properties, body,
                    store_factory=lambda: _PgStoreContext(database_url),
                    secret=secret,
                ),
            auto_ack=False,
        )
        logger.info("ERP_AMQP_NATIVE_CONSUMER_STARTED")
        def stop(_signal, _frame):
            if channel.is_open and channel.is_consuming:
                channel.stop_consuming()
        signal.signal(signal.SIGTERM, stop)
        channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()
        shutdown()


if __name__ == "__main__":
    main()
