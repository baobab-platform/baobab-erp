"""Postgres commercial-review audit store (ADR-ERP-024)."""

import json
from dataclasses import asdict
from datetime import UTC

from commercial_review.service import (
    CommercialReviewRecord,
    CommercialReviewRequest,
)


class PostgresCommercialReviewStore:
    def __init__(self, connection):
        self._connection = connection

    def find_by_idempotency_key(self, key):
        with self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT review_id, request_json, decided_at
                     FROM baobab.buyer_commercial_review
                    WHERE idempotency_key = %s""",
                (key,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        data = row[1]
        return CommercialReviewRecord(
            review_id=row[0],
            request=CommercialReviewRequest(**data),
            decided_at=row[2].astimezone(UTC),
        )

    def save(self, record):
        request = record.request
        with self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO baobab.buyer_commercial_review
                   (review_id, tenant_id, legal_entity_id, buyer_organisation_id,
                    canonical_organisation_id, business_partner_id, credit_status,
                    currency_code, payment_term_code, credit_limit_minor,
                    profile_reference, decision_reference, decided_by_principal_id,
                    idempotency_key, request_hash, request_json, decided_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                (
                    record.review_id, request.tenant_id, request.legal_entity_id,
                    request.buyer_organisation_id, request.canonical_organisation_id,
                    request.business_partner_id, request.credit_status,
                    request.currency_code, request.payment_term_code,
                    request.credit_limit_minor, request.profile_reference,
                    request.decision_reference, request.decided_by_principal_id,
                    request.idempotency_key, request.request_hash,
                    json.dumps(asdict(request)), record.decided_at,
                ),
            )
