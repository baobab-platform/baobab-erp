import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from events.cloudevent import CloudEvent
from security.signing import sign_body


@dataclass(frozen=True, slots=True)
class WebhookDestination:
    url: str
    signing_secret: str
    timeout_seconds: float = 10.0


class WebhookDeliveryError(Exception):
    pass


def deliver(event: CloudEvent, destination: WebhookDestination) -> None:
    """Deliver one canonical CloudEvent (structured mode) over signed HTTPS. Raises on any non-2xx response.

    Endpoint URL and signing secret are deployment configuration (ADR-ERP-005), never
    hard-coded here.
    """
    body = json.dumps(event.to_wire(), separators=(",", ":"), sort_keys=True).encode()
    signature = sign_body(body, destination.signing_secret)
    request = urllib.request.Request(
        destination.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/cloudevents+json", "X-Baobab-Signature": signature},
    )
    try:
        with urllib.request.urlopen(request, timeout=destination.timeout_seconds) as response:
            if response.status >= 300:
                raise WebhookDeliveryError(f"Unexpected status {response.status} from {destination.url}")
    except urllib.error.URLError as exc:
        raise WebhookDeliveryError(f"Delivery to {destination.url} failed: {exc}") from exc
