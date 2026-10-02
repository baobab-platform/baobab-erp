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

    def mark_retry(self, name, attempts, error):
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
