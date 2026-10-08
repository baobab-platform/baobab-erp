import json
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from events.cloudevent import new_event
from integration import signed_delivery as sd
from outbox.service import PermanentDeliveryError

KEY = sd.DeliveryKey("erp-delivery-2026-10", bytes(range(32)))
RECIPIENT = "baobab-control-plane"
NOW = datetime(2026, 10, 7, 17, 30, tzinfo=timezone.utc)


def _event():
    return new_event(type="com.baobab-platform.erp.provisioning.changed.v1", subject="provisioning:op-1",
                     correlation_id="0b9a7c1e-3b0e-4a57-9d4a-2a1d6a3f7e10", tenant_id="tn_abc123", data={"revision": 1})


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.body = b'{"a":1}'
        self.headers = sd.headers_for(KEY, RECIPIENT, self.body, NOW)
        self.keys = {KEY.key_id: KEY}

    def verify(self, **changes):
        headers = {**self.headers, **changes.pop("headers", {})}
        return sd.verify(self.keys, changes.pop("recipient", RECIPIENT), headers, changes.pop("body", self.body),
                         changes.pop("now", NOW))

    def test_a_genuine_delivery_verifies(self):
        self.assertTrue(self.verify())

    def test_every_binding_matters(self):
        self.assertFalse(self.verify(body=b'{"a":2}'), "the body is bound")
        self.assertFalse(self.verify(recipient="baobab-trade"), "the recipient is bound")
        self.assertFalse(self.verify(headers={"Baobab-Timestamp": "2026-10-07T17:30:01Z"}), "the timestamp is bound")
        self.assertFalse(self.verify(headers={"Baobab-Key-Id": "another-key"}), "an unregistered key is refused")
        other = sd.DeliveryKey(KEY.key_id, bytes(reversed(range(32))))
        self.assertFalse(sd.verify({KEY.key_id: other}, RECIPIENT, self.headers, self.body, NOW), "the secret is bound")

    def test_the_replay_window_is_300_seconds_either_way(self):
        self.assertTrue(self.verify(now=NOW + timedelta(seconds=300)))
        self.assertTrue(self.verify(now=NOW - timedelta(seconds=300)))
        self.assertFalse(self.verify(now=NOW + timedelta(seconds=301)))
        self.assertFalse(self.verify(now=NOW - timedelta(seconds=301)))

    def test_malformed_headers_never_verify(self):
        for header, value in (("Baobab-Signature", "0" * 64), ("Baobab-Signature", "hmac-sha256=" + "A" * 64),
                              ("Baobab-Signature", "none=" + "0" * 64), ("Baobab-Timestamp", "2026-10-07 17:30:00"),
                              ("Baobab-Timestamp", "2026-10-07T17:30:00+00:00"), ("Baobab-Key-Id", "")):
            with self.subTest(header, value=value):
                self.assertFalse(self.verify(headers={header: value}))

    def test_each_attempt_is_signed_afresh(self):
        later = sd.headers_for(KEY, RECIPIENT, self.body, NOW + timedelta(hours=5))
        self.assertNotEqual(later["Baobab-Signature"], self.headers["Baobab-Signature"])
        self.assertTrue(sd.verify(self.keys, RECIPIENT, later, self.body, NOW + timedelta(hours=5)))

    def test_keys_are_validated_and_the_secret_is_never_shown(self):
        for key_id in ("", "ab", "UPPER-case", "has space", "-leading", "a" * 65, "slash/key"):
            with self.subTest(key_id), self.assertRaises(sd.DeliveryConfigurationError):
                sd.DeliveryKey(key_id, bytes(32))
        with self.assertRaises(sd.DeliveryConfigurationError):
            sd.DeliveryKey("erp-delivery-2026-10", bytes(31))
        with self.assertRaises(sd.DeliveryConfigurationError):
            sd.DeliveryKey.from_base64("erp-delivery-2026-10", "not base64!")
        self.assertNotIn("\x01", repr(KEY))
        self.assertIn("redacted", repr(KEY))
        self.assertNotIn(str(list(KEY.secret)), repr(KEY))


class _Ingress(BaseHTTPRequestHandler):
    status, payload, redirect_to = 202, None, None
    seen: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).seen.append((dict(self.headers), body))
        if type(self).redirect_to:
            self.send_response(307)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        payload = type(self).payload if type(self).payload is not None else {
            "event_id": json.loads(body)["id"], "status": {202: "ACCEPTED", 200: "DUPLICATE"}.get(type(self).status, "ACCEPTED"),
            "received_at": "2026-10-07T17:30:00Z"}
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *_):
        pass


class TransportTests(unittest.TestCase):
    def setUp(self):
        _Ingress.status, _Ingress.payload, _Ingress.redirect_to, _Ingress.seen = 202, None, None, []
        self.server = HTTPServer(("127.0.0.1", 0), _Ingress)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.transport = sd.SignedDeliveryTransport(url=f"http://127.0.0.1:{self.server.server_port}/v1/integration/events",
                                                    key=KEY, clock=lambda: NOW)

    def test_it_posts_the_canonical_bytes_with_headers_a_consumer_verifies(self):
        event = _event()
        self.transport.deliver(event)
        received, body = _Ingress.seen[0]
        headers = {name.lower(): value for name, value in received.items()}
        self.assertEqual(body, sd.event_body(event))
        self.assertEqual(headers["content-type"], sd.CONTENT_TYPE)
        self.assertEqual(headers["x-correlation-id"], event.correlationid)
        self.assertTrue(sd.verify({KEY.key_id: KEY}, RECIPIENT, received, body, NOW))
        self.assertEqual(json.loads(body)["id"], event.id)

    def test_a_duplicate_receipt_is_a_delivery(self):
        _Ingress.status = 200
        self.transport.deliver(_event())

    def test_permanent_refusals_never_retry(self):
        for status in (400, 409, 413, 422):
            with self.subTest(status):
                _Ingress.status, _Ingress.payload = status, {"title": "no"}
                with self.assertRaises(PermanentDeliveryError) as raised:
                    self.transport.deliver(_event())
                self.assertIn(str(status), str(raised.exception))

    def test_other_failures_are_retried_and_reveal_nothing(self):
        for status in (401, 403, 404, 429, 500, 503):
            with self.subTest(status):
                _Ingress.status, _Ingress.payload = status, {"detail": "secret detail"}
                with self.assertRaises(sd.DeliveryError) as raised:
                    self.transport.deliver(_event())
                self.assertNotIn("secret detail", str(raised.exception))

    def test_a_receipt_that_does_not_acknowledge_this_event_is_not_a_delivery(self):
        for label, payload in (("another event", {"event_id": "11111111-1111-4111-8111-111111111111", "status": "ACCEPTED",
                                                  "received_at": "2026-10-07T17:30:00Z"}),
                               ("the wrong status for the HTTP status", {"event_id": None, "status": "DUPLICATE"}),
                               ("an empty body", {})):
            with self.subTest(label):
                _Ingress.status, _Ingress.payload = 202, payload
                with self.assertRaises(sd.DeliveryError):
                    self.transport.deliver(_event())

    def test_a_redirect_is_never_followed(self):
        _Ingress.redirect_to = "http://127.0.0.1:9/elsewhere"
        with self.assertRaises(sd.DeliveryError):
            self.transport.deliver(_event())
        self.assertEqual(len(_Ingress.seen), 1)

    def test_an_unreachable_ingress_is_retryable(self):
        dead = sd.SignedDeliveryTransport(url="http://127.0.0.1:9/", key=KEY, timeout_seconds=1)
        with self.assertRaises(sd.DeliveryError):
            dead.deliver(_event())

    def test_the_destination_must_be_https_or_local_and_carry_no_credentials(self):
        for url in ("http://ingress.example.com/", "ftp://x/", "https://user:pw@ingress.example.com/", "https:///path"):
            with self.subTest(url), self.assertRaises(sd.DeliveryConfigurationError):
                sd.SignedDeliveryTransport(url=url, key=KEY)
        sd.SignedDeliveryTransport(url="https://control.baobab-platform.com/v1/integration/events", key=KEY)


if __name__ == "__main__":
    unittest.main()
