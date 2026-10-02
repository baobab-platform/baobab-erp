import json
import re
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from events.cloudevent import CloudEvent, new_event
from integration.delivery_transport import WebhookDeliveryError, WebhookDestination, deliver

ISO_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _event() -> CloudEvent:
    return new_event(
        type="com.baobab-platform.erp.payment.accounting-changed.v1", subject="payment:pay-1",
        correlation_id="0b9a7c1e-3b0e-4a57-9d4a-2a1d6a3f7e10", data={"amount": 100}, tenant_id="tn_abc123",
    )


class _RecordingHandler(BaseHTTPRequestHandler):
    received_bodies: list[bytes] = []
    received_content_types: list[str] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.received_bodies.append(self.rfile.read(length))
        self.__class__.received_content_types.append(self.headers.get('Content-Type'))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class DeliveryTransportTests(unittest.TestCase):
    def setUp(self):
        _RecordingHandler.received_bodies = []
        _RecordingHandler.received_content_types = []
        self.server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def _destination(self) -> WebhookDestination:
        port = self.server.server_address[1]
        return WebhookDestination(url=f"http://127.0.0.1:{port}/webhook", signing_secret="secret")

    def test_time_is_rfc3339_on_the_wire(self):
        deliver(_event(), self._destination())
        body = json.loads(_RecordingHandler.received_bodies[0])
        self.assertRegex(body["time"], ISO_DATE_TIME)

    def test_structured_mode_content_type(self):
        deliver(_event(), self._destination())
        self.assertEqual(_RecordingHandler.received_content_types[0], "application/cloudevents+json")

    def test_wire_body_round_trips_through_cloudevent(self):
        event = _event()
        deliver(event, self._destination())
        body = json.loads(_RecordingHandler.received_bodies[0])
        self.assertEqual(CloudEvent.from_wire(body).to_wire(), event.to_wire())  # must not raise

    def test_non_2xx_response_raises(self):
        class FailingHandler(_RecordingHandler):
            def do_POST(self):
                self.send_response(500)
                self.end_headers()

        self.server.RequestHandlerClass = FailingHandler
        with self.assertRaises(WebhookDeliveryError):
            deliver(_event(), self._destination())


if __name__ == "__main__":
    unittest.main()
