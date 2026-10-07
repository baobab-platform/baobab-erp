import unittest

from events.cloudevent import CloudEvent, new_event
from outbox.service import backoff_seconds, dispatch_pending


def _event() -> CloudEvent:
    return new_event(
        type="com.baobab-platform.erp.invoice.changed.v1", subject="invoice:inv-1",
        correlation_id="0b9a7c1e-3b0e-4a57-9d4a-2a1d6a3f7e10", data={}, tenant_id="tn_abc123",
    )


class FakeRecord:
    def __init__(self, name: str, attempts: int = 0, status: str = "pending"):
        self.name = name
        self.attempts = attempts
        self.status = status
        self.event = _event()


class FakeStore:
    def __init__(self, records):
        self._records = {r.name: r for r in records}
        self.delivered = []
        self.retried = []
        self.dead_lettered = []

    def pending(self, limit: int = 100):
        return [r for r in self._records.values() if r.status in ("pending", "retry")][:limit]

    def mark_delivered(self, name):
        self.delivered.append(name)
        self._records[name].status = "delivered"

    def mark_retry(self, name, attempts, error, delay_seconds=0):
        self.retried.append((name, attempts, error))
        self._records[name].attempts = attempts
        self._records[name].status = "retry"

    def mark_dead_letter(self, name, attempts, error):
        self.dead_lettered.append((name, attempts, error))
        self._records[name].status = "dead_letter"


class AlwaysFailsTransport:
    def deliver(self, event):
        raise ConnectionError("no route to destination")


class AlwaysSucceedsTransport:
    def deliver(self, event):
        return None


class OutboxServiceTests(unittest.TestCase):
    def test_successful_delivery_marks_delivered(self):
        store = FakeStore([FakeRecord("evt-1")])
        dispatch_pending(store, AlwaysSucceedsTransport())
        self.assertEqual(store.delivered, ["evt-1"])

    def test_failed_delivery_below_max_attempts_retries(self):
        store = FakeStore([FakeRecord("evt-1", attempts=0)])
        dispatch_pending(store, AlwaysFailsTransport())
        self.assertEqual(len(store.retried), 1)
        self.assertEqual(store.retried[0][0], "evt-1")

    def test_failed_delivery_at_max_attempts_dead_letters(self):
        store = FakeStore([FakeRecord("evt-1", attempts=7)])
        dispatch_pending(store, AlwaysFailsTransport())
        self.assertEqual(len(store.dead_lettered), 1)

    def test_backoff_is_bounded(self):
        self.assertEqual(backoff_seconds(1), 2)
        self.assertEqual(backoff_seconds(20), 3600)


if __name__ == "__main__":
    unittest.main()


class RetryPolicyTests(unittest.TestCase):
    """FB-04b: permanent refusals dead-letter at once, and signed delivery is time-bound rather than attempt-bound."""

    def test_a_permanent_refusal_is_dead_lettered_on_the_first_try(self):
        from outbox.service import PermanentDeliveryError

        class Refuses:
            def deliver(self, event):
                raise PermanentDeliveryError("refused (HTTP 422)")

        store = FakeStore([FakeRecord("evt-1")])
        summary = dispatch_pending(store, Refuses())
        self.assertEqual((store.retried, [d[0] for d in store.dead_lettered]), ([], ["evt-1"]))
        self.assertEqual((summary.delivered, summary.retried, summary.dead_lettered), (0, 0, 1))

    def test_a_retry_carries_its_backoff(self):
        store = FakeStore([FakeRecord("evt-1", attempts=2)])
        dispatch_pending(store, AlwaysFailsTransport())
        self.assertEqual(store.retried[0][:2], ("evt-1", 3))

    def test_a_time_bound_policy_outlasts_the_attempt_count(self):
        from datetime import datetime, timedelta, timezone
        from outbox.service import RetryPolicy
        now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        policy = RetryPolicy(max_attempts=None, horizon=timedelta(hours=72))
        young = FakeRecord("evt-1", attempts=500)
        young.created_at = now - timedelta(hours=71)
        store = FakeStore([young])
        dispatch_pending(store, AlwaysFailsTransport(), policy, now=lambda: now)
        self.assertEqual((len(store.retried), store.dead_lettered), (1, []), "500 attempts is not the limit; 72 hours is")
        old = FakeRecord("evt-2")
        old.created_at = now - timedelta(hours=72)
        store = FakeStore([old])
        dispatch_pending(store, AlwaysFailsTransport(), policy, now=lambda: now)
        self.assertEqual(([d[0] for d in store.dead_lettered], store.retried), (["evt-2"], []))

    def test_an_event_past_the_horizon_is_still_delivered_if_it_succeeds(self):
        from datetime import datetime, timedelta, timezone
        from outbox.service import RetryPolicy
        now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        old = FakeRecord("evt-1")
        old.created_at = now - timedelta(days=30)
        store = FakeStore([old])
        dispatch_pending(store, AlwaysSucceedsTransport(), RetryPolicy(max_attempts=None, horizon=timedelta(hours=72)), now=lambda: now)
        self.assertEqual(store.delivered, ["evt-1"])

    def test_a_retry_that_became_due_after_the_horizon_is_dead_lettered_without_another_attempt(self):
        from datetime import datetime, timedelta, timezone
        from outbox.service import RetryPolicy

        class MustNotBeCalled:
            def deliver(self, event):
                raise AssertionError("an expired retry must not be attempted")

        now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        expired = FakeRecord("evt-1", attempts=40, status="retry")
        expired.created_at = now - timedelta(hours=72, minutes=1)
        store = FakeStore([expired])
        summary = dispatch_pending(store, MustNotBeCalled(), RetryPolicy(max_attempts=None, horizon=timedelta(hours=72)), now=lambda: now)
        self.assertEqual(([d[0] for d in store.dead_lettered], store.delivered, summary.dead_lettered), (["evt-1"], [], 1))
        # An event never attempted always gets its first try, however old.
        fresh = FakeRecord("evt-2")
        fresh.created_at = now - timedelta(days=30)
        store = FakeStore([fresh])
        dispatch_pending(store, AlwaysSucceedsTransport(), RetryPolicy(max_attempts=None, horizon=timedelta(hours=72)), now=lambda: now)
        self.assertEqual(store.delivered, ["evt-2"])
