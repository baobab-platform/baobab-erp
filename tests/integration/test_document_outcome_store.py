"""PostgresDocumentOutcomeStore advances a document's revision only when what ERP observed changed (db/migrations/0022)."""
import unittest
from datetime import datetime, timedelta, timezone

from _postgres import connect
from order_to_cash.outcome_store import PostgresDocumentOutcomeStore

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
KEY = {"tenant_id": "tn_01k4m7x9q2v6c8r3d5f1h0j4", "document_type": "invoice", "document_id": "erp_inv0000000001"}


class DocumentOutcomeStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = connect()
        self.addCleanup(self.db.close)  # never committed: the connection rolls back
        self.store = PostgresDocumentOutcomeStore(self.db)

    def advance(self, status="posted", detail=None, at=NOW):
        return self.store.advance(**KEY, status=status, detail=detail or {"number": "INV-1"}, now=at)

    def test_first_sight_is_revision_one_and_a_repeat_changes_nothing(self):
        first = self.advance()
        again = self.advance(at=NOW + timedelta(minutes=5))
        self.assertEqual((first.revision, first.changed, first.first_seen_at), (1, True, NOW))
        self.assertEqual((again.revision, again.changed, again.first_seen_at), (1, False, NOW))

    def test_a_changed_status_or_detail_is_the_next_revision_and_keeps_first_seen(self):
        self.advance()
        paid = self.advance("paid", at=NOW + timedelta(hours=1))
        reworded = self.advance("paid", {"number": "INV-2"}, at=NOW + timedelta(hours=2))
        self.assertEqual((paid.revision, paid.changed, paid.first_seen_at), (2, True, NOW))
        self.assertEqual((reworded.revision, reworded.changed), (3, True))

    def test_a_status_never_moves_backwards(self):
        self.advance("paid")
        stale = self.advance("posted", at=NOW + timedelta(hours=1))
        self.assertEqual((stale.revision, stale.changed), (1, False))

    def test_documents_are_independent(self):
        self.advance()
        other = self.store.advance(**{**KEY, "document_type": "payment"}, status="posted", detail={}, now=NOW)
        self.assertEqual((other.revision, other.changed), (1, True))
