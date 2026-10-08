"""Signed HTTPS delivery of a canonical event to a consumer's event ingress (Shared events/v1/signed-delivery.schema.json,
docs/architecture/signed-event-delivery.md).

The event is the contract and this is only one transport for it. The body is the canonical envelope's exact bytes
(Content-Type application/cloudevents+json). The signature is HMAC-SHA256, keyed with the delivery key's secret, over

    baobab-event-delivery-v1 LF <recipient> LF <key id> LF <timestamp> LF <lowercase hex SHA-256 of the body>

so it binds the recipient, who signed, when and exactly what. Every attempt is signed afresh (a retry hours later is never
stale), the algorithm is named in the signature so a stronger scheme can replace it without changing the headers, and no
log line, exception or error carries the secret, the signature or the event data.

Delivery is at-least-once. A 2xx is the consumer saying the event is durably recorded: 202 ``ACCEPTED`` the first time, 200
``DUPLICATE`` for a redelivery. 400, 409, 413 and 422 are permanent (a retry cannot change them) and dead-letter at once;
anything else is retried by the outbox policy.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

from events.cloudevent import CloudEvent
from outbox.service import PermanentDeliveryError

SIGNING_LABEL = "baobab-event-delivery-v1"
ALGORITHM = "hmac-sha256"
REPLAY_WINDOW = timedelta(seconds=300)
MIN_SECRET_BYTES = 32
MAX_BODY_BYTES = 1024 * 1024
PERMANENT_STATUSES = frozenset({400, 409, 413, 422})
CONTENT_TYPE = "application/cloudevents+json"

_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_TIMESTAMP = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\dZ$")
_SIGNATURE = re.compile(r"^hmac-sha256=[0-9a-f]{64}$")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class DeliveryConfigurationError(ValueError):
    """The delivery key or destination is not usable. Never carries the secret."""


class DeliveryError(Exception):
    """A delivery attempt failed in a way that is worth retrying."""


@dataclass(frozen=True, slots=True)
class DeliveryKey:
    key_id: str
    secret: bytes

    def __post_init__(self) -> None:
        if not _KEY_ID.fullmatch(self.key_id):
            raise DeliveryConfigurationError("the delivery key id must match ^[a-z0-9][a-z0-9._-]{2,63}$")
        if len(self.secret) < MIN_SECRET_BYTES:
            raise DeliveryConfigurationError(f"the delivery secret must be at least {MIN_SECRET_BYTES} bytes")

    def __repr__(self) -> str:  # the secret never appears in a log or a traceback
        return f"DeliveryKey(key_id={self.key_id!r}, secret=<redacted>)"

    @classmethod
    def from_base64(cls, key_id: str, secret_b64: str) -> "DeliveryKey":
        try:
            secret = base64.b64decode(secret_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DeliveryConfigurationError("the delivery secret must be standard base64") from exc
        return cls(key_id, secret)


def format_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def signing_string(recipient: str, key_id: str, timestamp: str, body: bytes) -> bytes:
    return "\n".join((SIGNING_LABEL, recipient, key_id, timestamp, hashlib.sha256(body).hexdigest())).encode()


def sign(key: DeliveryKey, recipient: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(key.secret, signing_string(recipient, key.key_id, timestamp, body), hashlib.sha256).hexdigest()
    return f"{ALGORITHM}={digest}"


def headers_for(key: DeliveryKey, recipient: str, body: bytes, now: datetime) -> dict[str, str]:
    timestamp = format_timestamp(now)
    return {"Baobab-Key-Id": key.key_id, "Baobab-Timestamp": timestamp,
            "Baobab-Signature": sign(key, recipient, timestamp, body)}


def verify(keys: dict[str, DeliveryKey], recipient: str, headers: dict[str, str], body: bytes, now: datetime) -> bool:
    """What a consumer does, in its order, for tests and for any ERP-side consumer: a registered key, a timestamp inside the
    replay window, then the signature in constant time. False for every failure; the reason is never revealed."""
    headers = {name.lower(): value for name, value in headers.items()}  # header names are case-insensitive
    key = keys.get(headers.get("baobab-key-id", ""))
    timestamp, supplied = headers.get("baobab-timestamp", ""), headers.get("baobab-signature", "")
    if key is None or not _TIMESTAMP.fullmatch(timestamp) or not _SIGNATURE.fullmatch(supplied):
        return False
    signed_at = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if abs(now - signed_at) > REPLAY_WINDOW:
        return False
    return hmac.compare_digest(sign(key, recipient, timestamp, body), supplied)


def event_body(event: CloudEvent) -> bytes:
    """The exact bytes of the envelope: stable across attempts so every retry carries the same body."""
    return json.dumps(event.to_wire(), separators=(",", ":"), sort_keys=True).encode()


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):  # a signed request is never replayed at another address
        return None


@dataclass(frozen=True, slots=True)
class SignedDeliveryTransport:
    """Delivers one event per call to ``url`` (an event ingress), signed with ``key`` for ``recipient``."""
    url: str
    key: DeliveryKey
    recipient: str = "baobab-control-plane"
    timeout_seconds: float = 10.0
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        parts = urlsplit(self.url)
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS):
            raise DeliveryConfigurationError("the event ingress must be https (http only for a local address)")
        if not parts.hostname or parts.username or parts.password:
            raise DeliveryConfigurationError("the event ingress must be a host URL without credentials")

    def deliver(self, event: CloudEvent) -> None:
        body = event_body(event)
        if len(body) > MAX_BODY_BYTES:
            raise PermanentDeliveryError("the event exceeds the 1 MiB delivery limit")
        headers = {"Content-Type": CONTENT_TYPE, "X-Correlation-ID": event.correlationid,
                   **headers_for(self.key, self.recipient, body, self.clock())}
        if event.traceparent:
            headers["traceparent"] = event.traceparent
        request = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        opener = urllib.request.build_opener(_NoRedirects)
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                status, payload = response.status, response.read(65536)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in PERMANENT_STATUSES:
                raise PermanentDeliveryError(f"the event ingress refused the event permanently (HTTP {exc.code})") from None
            raise DeliveryError(f"the event ingress answered HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DeliveryError(f"delivery to the event ingress failed: {type(exc).__name__}") from None
        self._check_receipt(event, status, payload)

    @staticmethod
    def _check_receipt(event: CloudEvent, status: int, payload: bytes) -> None:
        expected = {202: "ACCEPTED", 200: "DUPLICATE"}.get(status)
        if expected is None:
            raise DeliveryError(f"the event ingress answered an unexpected HTTP {status}")
        try:
            receipt = json.loads(payload)
        except ValueError:
            raise DeliveryError("the event ingress receipt is not JSON") from None
        if not isinstance(receipt, dict) or receipt.get("event_id") != event.id or receipt.get("status") != expected:
            # A 2xx that does not acknowledge exactly this event is not a durable acceptance of it.
            raise DeliveryError("the event ingress receipt does not acknowledge this event")
