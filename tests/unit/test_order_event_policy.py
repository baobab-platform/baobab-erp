"""The pure parts of order-event execution: the payload reader, the retry/block budgets and the deterministic ERP order id."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from order_to_cash.execution_policy import (BLOCKED_DELAY_SECONDS, BLOCKED_HORIZON, MAX_ATTEMPTS, RETRY_CEILING_SECONDS,
                                           Outcome, erp_order_id, failure_outcome, retry_delay_seconds)
from order_to_cash.placed_order import PayloadError, parse_placed_order

GOOD = {
    "legal_entity_id": "ZURIBEANS", "commerce_order_id": "order_01k4n6w5", "order_version": 1, "customer_id": "customer_01k4n6x2",
    "currency": "USD",
    "lines": [{"line_id": "line_01k4n715", "sku_id": "sku_01k4n72a", "quantity": {"value": "12", "unit": "EA"},
               "unit_price": {"amount": "25.00", "currency": "USD"}}],
}
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


class ParsePlacedOrderTests(unittest.TestCase):
    def test_the_shared_example_shape_parses(self):
        order = parse_placed_order(GOOD)
        self.assertEqual((order.commerce_order_id, order.order_version, order.currency), ("order_01k4n6w5", 1, "USD"))
        self.assertEqual(order.lines[0].quantity, "12")
        self.assertEqual(order.lines[0].unit_price, "25.00")

    def _broken(self, edit):
        data = copy.deepcopy(GOOD)
        edit(data)
        with self.assertRaises(PayloadError):
            parse_placed_order(data)

    def test_malformed_payloads_are_refused(self):
        cases = {
            "not an object": lambda d: d.clear() or d.update(lines=1),
            "no lines": lambda d: d.update(lines=[]),
            "bad legal entity": lambda d: d.update(legal_entity_id="zuri beans"),
            "version zero": lambda d: d.update(order_version=0),
            "version bool": lambda d: d.update(order_version=True),
            "version string": lambda d: d.update(order_version="1"),
            "order id with space": lambda d: d.update(commerce_order_id="order 1"),
            "customer missing": lambda d: d.pop("customer_id"),
            "currency lowercase": lambda d: d.update(currency="usd"),
            "price in other currency": lambda d: d["lines"][0]["unit_price"].update(currency="EUR"),
            "quantity zero": lambda d: d["lines"][0]["quantity"].update(value="0"),
            "quantity number not string": lambda d: d["lines"][0]["quantity"].update(value=12),
            "quantity not a decimal": lambda d: d["lines"][0]["quantity"].update(value="twelve"),
            "negative price": lambda d: d["lines"][0]["unit_price"].update(amount="-1"),
            "nan price": lambda d: d["lines"][0]["unit_price"].update(amount="NaN"),
            "unit missing": lambda d: d["lines"][0]["quantity"].pop("unit"),
            "duplicate line": lambda d: d["lines"].append(copy.deepcopy(d["lines"][0])),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self._broken(edit)

    def test_a_non_object_is_refused(self):
        for value in (None, [], "x", 1):
            with self.subTest(value), self.assertRaises(PayloadError):
                parse_placed_order(value)

    def test_the_reason_never_echoes_payload_content(self):
        data = copy.deepcopy(GOOD)
        data["customer_id"] = "secret customer name"
        with self.assertRaises(PayloadError) as caught:
            parse_placed_order(data)
        self.assertNotIn("secret", str(caught.exception))


class BudgetTests(unittest.TestCase):
    def test_retry_backoff_doubles_to_a_ceiling(self):
        self.assertEqual([retry_delay_seconds(n) for n in (1, 2, 3, 4)], [30, 60, 120, 240])
        self.assertEqual(retry_delay_seconds(8), RETRY_CEILING_SECONDS)
        self.assertEqual(retry_delay_seconds(60), RETRY_CEILING_SECONDS)

    def test_the_attempt_budget_spans_hours_not_minutes(self):
        total = sum(retry_delay_seconds(n) for n in range(1, MAX_ATTEMPTS))
        self.assertGreater(total, 12 * 3600)

    def test_a_transient_failure_is_retried_until_the_budget_is_spent(self):
        retry = Outcome("retry", "ENGINE_UNAVAILABLE")
        early = failure_outcome(retry, attempts=3, received_at=NOW, now=NOW)
        self.assertEqual((early.status, early.delay_seconds), ("retry", 120))
        last = failure_outcome(retry, attempts=MAX_ATTEMPTS, received_at=NOW, now=NOW)
        self.assertEqual((last.status, last.code, last.detail), ("dead_letter", "ATTEMPTS_EXHAUSTED", "ENGINE_UNAVAILABLE"))

    def test_a_block_is_slow_until_its_horizon_then_a_dead_letter(self):
        blocked = Outcome("blocked", "CUSTOMER_UNMAPPED")
        slow = failure_outcome(blocked, attempts=40, received_at=NOW, now=NOW + BLOCKED_HORIZON)
        self.assertEqual((slow.status, slow.delay_seconds), ("blocked", BLOCKED_DELAY_SECONDS))  # attempts do not exhaust a block
        dead = failure_outcome(blocked, attempts=1, received_at=NOW, now=NOW + BLOCKED_HORIZON + timedelta(seconds=1))
        self.assertEqual((dead.status, dead.code), ("dead_letter", "BLOCKED_HORIZON_EXCEEDED"))

    def test_contention_keeps_its_fixed_delay_and_refund(self):
        contended = Outcome("retry", "ORDER_CONTENDED", delay_seconds=5, refund_attempt=True)
        kept = failure_outcome(contended, attempts=MAX_ATTEMPTS - 1, received_at=NOW, now=NOW)
        self.assertEqual((kept.delay_seconds, kept.refund_attempt), (5, True))

    def test_settled_outcomes_pass_through(self):
        for outcome in (Outcome("processed", "ALREADY_EXECUTED"), Outcome("dead_letter", "PAYLOAD_INVALID")):
            self.assertEqual(failure_outcome(outcome, attempts=99, received_at=NOW - BLOCKED_HORIZON * 2, now=NOW), outcome)


class ErpOrderIdTests(unittest.TestCase):
    def test_it_is_deterministic_per_tenant_and_order_and_has_the_public_shape(self):
        first = erp_order_id("tn_a1", "order_1")
        self.assertEqual(first, erp_order_id("tn_a1", "order_1"))
        self.assertNotEqual(first, erp_order_id("tn_a2", "order_1"))
        self.assertNotEqual(first, erp_order_id("tn_a1", "order_2"))
        self.assertRegex(first, r"^erp_[a-z0-9]{4,59}$")


if __name__ == "__main__":
    unittest.main()
