"""Exercises RestIdempiereClient against a real local HTTP server that reproduces
the exact request/response shapes from the bxservice/idempiere-rest OpenAPI spec
(auth, models list/get/create/update, error envelope) -- not a mock of urllib
internals, so a wrong path/header/body shape actually fails the test.
"""

import json
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from integration.idempiere_client import (
    IdempiereApiError,
    IdempiereAuthenticationError,
    IdempiereClientError,
    IdempiereCredentials,
    RestIdempiereClient,
)

VALID_USERNAME = "GardenAdmin"
VALID_PASSWORD = "GardenAdmin"


class _State:
    """Shared, per-test mutable state the fake handler reads/writes."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.tokens_issued = 0
        self.refresh_calls = 0
        self.force_401_once_on_path = None
        self.records = {("c_bpartner", 119): {"id": 119, "Name": "Acme"}}
        self.last_request_body = None
        self.last_auth_header = None


class _FakeIdempiereHandler(BaseHTTPRequestHandler):
    state: _State = None  # set per test via server.state

    def log_message(self, *args):
        pass

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _issue_token(self):
        self.state.tokens_issued += 1
        self._send_json(
            200,
            {
                "userId": 100,
                "language": "en_US",
                "menuTreeId": 10,
                "token": f"token-{self.state.tokens_issued}",
                "refresh_token": f"refresh-{self.state.tokens_issued}",
            },
        )

    def do_POST(self):
        body = self._read_body()
        if self.path == "/auth/tokens":
            if body.get("userName") != VALID_USERNAME or body.get("password") != VALID_PASSWORD:
                self._send_json(
                    401, {"title": "Authenticate error", "status": 401, "detail": "Invalid User ID or Password"}
                )
                return
            self._issue_token()
            return

        if self.path == "/auth/refresh":
            self.state.refresh_calls += 1
            if not body.get("refresh_token", "").startswith("refresh-"):
                self._send_json(401, {"title": "Authenticate error", "status": 401, "detail": "Invalid refresh token"})
                return
            self._issue_token()
            return

        if self.path.startswith("/models/"):
            self._require_auth_and_dispatch("POST", body)
            return

        if self.path.startswith("/processes/"):
            auth_header = self.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer token-"):
                self._send_json(401, {"title": "Authenticate error", "status": 401, "detail": "missing/invalid token"})
                return
            self.state.last_request_body = body
            self._send_json(200, {"summary": "Process completed", "isError": False})
            return

        self._send_json(404, {"title": "Not Found", "status": 404, "detail": "no such route"})

    def do_GET(self):
        self._require_auth_and_dispatch("GET", None)

    def do_PUT(self):
        body = self._read_body()
        self._require_auth_and_dispatch("PUT", body)

    def _require_auth_and_dispatch(self, method: str, body: dict | None):
        auth_header = self.headers.get("Authorization", "")
        self.state.last_auth_header = auth_header
        if self.state.force_401_once_on_path == self.path:
            self.state.force_401_once_on_path = None
            self._send_json(401, {"title": "Authenticate error", "status": 401, "detail": "token expired"})
            return
        if not auth_header.startswith("Bearer token-"):
            self._send_json(401, {"title": "Authenticate error", "status": 401, "detail": "missing/invalid token"})
            return

        self.state.last_request_body = body
        parts = self.path.strip("/").split("/")  # ["models", "c_bpartner"] or [..., "119"]
        table = parts[1]

        if method == "GET" and len(parts) == 3:
            record = self.state.records.get((table, int(parts[2])))
            if record is None:
                self._send_json(404, {"title": "Not Found", "status": 404, "detail": "no such record"})
                return
            self._send_json(200, record)
            return

        if method == "POST" and len(parts) == 2:
            new_id = max((rid for (t, rid) in self.state.records if t == table), default=0) + 1
            record = {"id": new_id, **body}
            self.state.records[(table, new_id)] = record
            self._send_json(201, record)
            return

        if method == "PUT" and len(parts) == 3:
            record_id = int(parts[2])
            if (table, record_id) not in self.state.records:
                self._send_json(404, {"title": "Not Found", "status": 404, "detail": "no such record"})
                return
            self.state.records[(table, record_id)].update(body)
            self._send_json(200, self.state.records[(table, record_id)])
            return

        self._send_json(404, {"title": "Not Found", "status": 404, "detail": "unhandled route"})


class RestIdempiereClientTests(unittest.TestCase):
    def setUp(self):
        self.state = _State()
        _FakeIdempiereHandler.state = self.state
        self.server = HTTPServer(("127.0.0.1", 0), _FakeIdempiereHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)

    def _client(self, username=VALID_USERNAME, password=VALID_PASSWORD) -> RestIdempiereClient:
        port = self.server.server_address[1]
        credentials = IdempiereCredentials(
            base_url=f"http://127.0.0.1:{port}",
            username=username,
            password=password,
            client_id=11,
            role_id=102,
            organization_id=11,
            warehouse_id=103,
        )
        return RestIdempiereClient(credentials)

    def test_get_record_authenticates_then_fetches(self):
        client = self._client()
        record = client.get_record("c_bpartner", 119)
        self.assertEqual(record["Name"], "Acme")
        self.assertEqual(self.state.tokens_issued, 1)

    def test_create_record_returns_new_id(self):
        client = self._client()
        new_id = client.create_record("c_tax", {"Name": "MyGST", "Rate": "7.0"})
        self.assertIsInstance(new_id, int)
        self.assertEqual(self.state.records[("c_tax", new_id)]["Name"], "MyGST")

    def test_update_record_sends_fields_and_succeeds(self):
        client = self._client()
        client.update_record("c_bpartner", 119, {"Name": "Acme Updated"})
        self.assertEqual(self.state.records[("c_bpartner", 119)]["Name"], "Acme Updated")
        self.assertEqual(self.state.last_request_body, {"Name": "Acme Updated"})

    def test_execute_process_uses_process_boundary(self):
        client = self._client()
        result = client.execute_process(104, {"record-id": 119})
        self.assertEqual(result["summary"], "Process completed")
        self.assertEqual(self.state.last_request_body, {"record-id": 119})

    def test_wrong_credentials_raise_authentication_error(self):
        client = self._client(password="wrong")
        with self.assertRaises(IdempiereAuthenticationError):
            client.get_record("c_bpartner", 119)

    def test_missing_record_raises_api_error_with_status(self):
        client = self._client()
        with self.assertRaises(IdempiereApiError) as ctx:
            client.get_record("c_bpartner", 999999)
        self.assertEqual(ctx.exception.status, 404)

    def test_expired_token_triggers_one_retry_with_fresh_login(self):
        client = self._client()
        client.get_record("c_bpartner", 119)  # establishes a token
        self.state.force_401_once_on_path = "/models/c_bpartner/119"

        record = client.get_record("c_bpartner", 119)  # should transparently re-auth and succeed

        self.assertEqual(record["Name"], "Acme")
        self.assertEqual(self.state.tokens_issued, 2)

    def test_expired_token_uses_refresh_not_full_relogin(self):
        client = self._client()
        client.get_record("c_bpartner", 119)  # establishes token-1 / refresh-1
        client._token_expires_at = 0  # simulate real 1-hour expiry without waiting

        client.get_record("c_bpartner", 119)

        self.assertEqual(self.state.refresh_calls, 1)
        self.assertEqual(self.state.tokens_issued, 2)  # refresh also issues a new token

    def test_invalid_refresh_token_falls_back_to_full_login(self):
        client = self._client()
        client.get_record("c_bpartner", 119)
        client._token_expires_at = 0
        client._refresh_token = "refresh-stale-and-invalid"

        record = client.get_record("c_bpartner", 119)

        self.assertEqual(record["Name"], "Acme")
        self.assertEqual(self.state.refresh_calls, 1)
        self.assertEqual(self.state.tokens_issued, 2)

    def test_unreachable_server_raises_client_error(self):
        credentials = IdempiereCredentials(
            base_url="http://127.0.0.1:1",  # nothing listens on port 1
            username=VALID_USERNAME,
            password=VALID_PASSWORD,
            client_id=11,
            role_id=102,
            organization_id=11,
            timeout_seconds=2.0,
        )
        client = RestIdempiereClient(credentials)
        with self.assertRaises(IdempiereClientError):
            client.get_record("c_bpartner", 119)


if __name__ == "__main__":
    unittest.main()
