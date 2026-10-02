"""The constrained list/query operation of RestIdempiereClient: typed filters only, paging, and a hard cap instead of silent
truncation. Runs against a real local HTTP server that serves the REST plugin's list envelope."""
import json
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from integration.idempiere_client import (
    Eq, IdempiereClientError, IdempiereCredentials, RestIdempiereClient, UnconfiguredIdempiereClient,
    IdempiereEndpoint, build_filter)


class BuildFilterTests(unittest.TestCase):
    def test_conditions_are_typed_and_joined_with_and(self):
        self.assertEqual(build_filter([Eq("M_Product_ID", 1000012), Eq("IsSOTrx", True), Eq("Name", "a")]),
                         "M_Product_ID eq 1000012 and IsSOTrx eq true and Name eq 'a'")

    def test_a_string_value_cannot_break_out_of_its_quotes(self):
        self.assertEqual(build_filter([Eq("Name", "x' or 1 eq 1 or Name eq 'y")]),
                         "Name eq 'x'' or 1 eq 1 or Name eq ''y'")

    def test_a_column_must_be_a_plain_name(self):
        for column in ("M_Product_ID eq 1 or 1", "a b", "", "1abc", "A;B", "A/B"):
            with self.subTest(column), self.assertRaises(ValueError):
                build_filter([Eq(column, 1)])

    def test_only_numbers_booleans_and_strings_are_values(self):
        for value in (1.5, None, [1], {"a": 1}):
            with self.subTest(value), self.assertRaises(TypeError):
                build_filter([Eq("A", value)])
        with self.assertRaises(ValueError):
            build_filter([Eq("A", "line\nbreak")])


class _State:
    def __init__(self, total=0):
        self.requests = []
        self.total = total
        self.list_body = None


class _Handler(BaseHTTPRequestHandler):
    state: _State = None

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._send(200, {"userId": 1, "token": "token-1", "refresh_token": "refresh-1"})

    def do_GET(self):
        split = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(split.query).items()}
        self.state.requests.append((split.path, params))
        if self.state.list_body is not None:
            return self._send(200, self.state.list_body)
        skip, top = int(params["$skip"]), int(params["$top"])
        records = [{"id": n} for n in range(skip, min(skip + top, self.state.total))]
        self._send(200, {"page-count": 1, "records-size": len(records), "skip-records": skip,
                         "row-count": self.state.total, "array-count": len(records), "records": records})


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.state = _State()
        _Handler.state = self.state
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.client = RestIdempiereClient(IdempiereCredentials(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}", username="u", password="p",
            client_id=11, role_id=1, organization_id=1))

    def test_filter_select_and_paging_reach_the_plugin_as_query_parameters(self):
        self.state.total = 250
        rows = self.client.query("M_StorageOnHand", [Eq("M_Product_ID", 7), Eq("Name", "o'brien")], ["QtyOnHand", "Updated"])
        self.assertEqual(len(rows), 250)
        self.assertEqual([r[1]["$skip"] for r in self.state.requests], ["0", "100", "200"])
        path, params = self.state.requests[0]
        self.assertEqual(path, "/models/M_StorageOnHand")
        self.assertEqual(params["$filter"], "M_Product_ID eq 7 and Name eq 'o''brien'")
        self.assertEqual((params["$select"], params["$top"]), ("QtyOnHand,Updated", "100"))

    def test_an_empty_result_is_an_empty_list(self):
        self.assertEqual(self.client.query("M_Locator", [Eq("M_Warehouse_ID", 1)], ["M_Locator_ID"]), [])

    def test_a_result_over_the_cap_is_an_error_not_a_truncated_list(self):
        self.state.total = 100000
        with self.assertRaises(IdempiereClientError):
            self.client.query("M_StorageOnHand", [Eq("M_Product_ID", 7)], ["QtyOnHand"])

    def test_a_response_without_a_records_array_is_an_error(self):
        self.state.list_body = {"unexpected": True}
        with self.assertRaises(IdempiereClientError):
            self.client.query("M_Locator", [Eq("M_Warehouse_ID", 1)], ["M_Locator_ID"])

    def test_table_and_select_must_be_plain_names(self):
        for table, select in (("M_Locator?x=1", ["A"]), ("M_Locator", ["A,B"]), ("M_Locator", ["A eq 1"])):
            with self.subTest(table=table, select=select), self.assertRaises(ValueError):
                self.client.query(table, [], select)

    def test_the_unconfigured_client_refuses_to_query(self):
        with self.assertRaises(IdempiereClientError):
            UnconfiguredIdempiereClient(IdempiereEndpoint("(unconfigured)", 1, 0)).query("M_Locator", [], ["A"])


if __name__ == "__main__":
    unittest.main()
