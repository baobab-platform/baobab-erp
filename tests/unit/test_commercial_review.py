import unittest

from commercial_review.service import (
    CommercialReviewError,
    CommercialReviewRequest,
    decide_commercial_review,
)


class FakeStore:
    def __init__(self):
        self.by_key = {}

    def find_by_idempotency_key(self, key):
        return self.by_key.get(key)

    def save(self, record):
        self.by_key[record.request.idempotency_key] = record


def request(**overrides):
    values = dict(
        tenant_id="tn_zuribeans",
        legal_entity_id="le_zuribeans_za",
        buyer_organisation_id="buyerorg_1",
        canonical_organisation_id="org_buyer_1",
        business_partner_id="erp_bp123",
        credit_status="APPROVED",
        currency_code="ZAR",
        payment_term_code="PREPAYMENT",
        credit_limit_minor=0,
        profile_reference="ERP-PROFILE-1",
        decision_reference="ERP-DECISION-1",
        decided_by_principal_id="prn_finance_1",
        idempotency_key="commercial-review-0001",
        request_hash="a" * 64,
        correlation_id="corr-1",
    )
    values.update(overrides)
    return CommercialReviewRequest(**values)


class CommercialReviewTests(unittest.TestCase):
    def test_approved_prepayment_profile_emits_complete_event(self):
        record, event, replayed = decide_commercial_review(request(), store=FakeStore())
        self.assertFalse(replayed)
        self.assertEqual(record.request.credit_limit_minor, 0)
        self.assertEqual(event.payload["source_system"], "ERP")
        self.assertEqual(event.payload["legal_entity_id"], "le_zuribeans_za")
        self.assertEqual(event.payload["payment_term_code"], "PREPAYMENT")

    def test_approved_profile_requires_payment_terms(self):
        with self.assertRaises(CommercialReviewError):
            request(payment_term_code=None).validate()

    def test_idempotent_replay_returns_same_review(self):
        store = FakeStore()
        first, _, _ = decide_commercial_review(request(), store=store)
        second, _, replayed = decide_commercial_review(request(), store=store)
        self.assertTrue(replayed)
        self.assertEqual(first.review_id, second.review_id)

    def test_idempotency_payload_mismatch_fails(self):
        store = FakeStore()
        decide_commercial_review(request(), store=store)
        with self.assertRaisesRegex(CommercialReviewError, "payload mismatch"):
            decide_commercial_review(request(request_hash="b" * 64), store=store)


if __name__ == "__main__":
    unittest.main()
