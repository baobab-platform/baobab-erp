"""ERP-owned buyer commercial review decision (ADR-ERP-024)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import uuid4

from events.envelope import EventEnvelope

CreditStatus = Literal["APPROVED", "ON_HOLD", "REJECTED"]
EVENT_TYPE = "com.baobab-platform.customer.buyer-commercial-profile.changed.v1"


class CommercialReviewError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommercialReviewRequest:
    tenant_id: str
    legal_entity_id: str
    buyer_organisation_id: str
    canonical_organisation_id: str
    business_partner_id: str
    credit_status: CreditStatus
    currency_code: str
    payment_term_code: str | None
    credit_limit_minor: int | None
    profile_reference: str
    decision_reference: str
    decided_by_principal_id: str
    idempotency_key: str
    request_hash: str
    correlation_id: str

    def validate(self) -> None:
        required = {
            "tenant_id": self.tenant_id,
            "legal_entity_id": self.legal_entity_id,
            "buyer_organisation_id": self.buyer_organisation_id,
            "canonical_organisation_id": self.canonical_organisation_id,
            "business_partner_id": self.business_partner_id,
            "profile_reference": self.profile_reference,
            "decision_reference": self.decision_reference,
            "decided_by_principal_id": self.decided_by_principal_id,
            "idempotency_key": self.idempotency_key,
            "request_hash": self.request_hash,
            "correlation_id": self.correlation_id,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise CommercialReviewError(f"missing required fields: {', '.join(missing)}")
        if self.credit_status not in ("APPROVED", "ON_HOLD", "REJECTED"):
            raise CommercialReviewError("invalid credit_status")
        if len(self.currency_code) != 3 or not self.currency_code.isalpha():
            raise CommercialReviewError("currency_code must be ISO 4217")
        if self.credit_limit_minor is not None and self.credit_limit_minor < 0:
            raise CommercialReviewError("credit_limit_minor cannot be negative")
        if self.credit_status == "APPROVED" and not self.payment_term_code:
            raise CommercialReviewError("approved profile requires payment_term_code")


@dataclass(frozen=True, slots=True)
class CommercialReviewRecord:
    review_id: str
    request: CommercialReviewRequest
    decided_at: datetime


class CommercialReviewStore(Protocol):
    def find_by_idempotency_key(self, key: str) -> CommercialReviewRecord | None: ...
    def save(self, record: CommercialReviewRecord) -> None: ...


def decide_commercial_review(
    request: CommercialReviewRequest,
    *,
    store: CommercialReviewStore,
) -> tuple[CommercialReviewRecord, EventEnvelope, bool]:
    request.validate()
    replay = store.find_by_idempotency_key(request.idempotency_key)
    if replay is not None:
        if replay.request.request_hash != request.request_hash:
            raise CommercialReviewError("Idempotency-Key payload mismatch")
        return replay, _event_for(replay), True

    record = CommercialReviewRecord(
        review_id=f"erpcr_{uuid4().hex}",
        request=request,
        decided_at=datetime.now(UTC),
    )
    store.save(record)
    return record, _event_for(record), False


def _event_for(record: CommercialReviewRecord) -> EventEnvelope:
    request = record.request
    return EventEnvelope(
        event_id=str(uuid4()),
        event_type=EVENT_TYPE,
        schema_version="1.0",
        occurred_at=record.decided_at,
        source="urn:baobab-platform:baobab-erp",
        correlation_id=request.correlation_id,
        tenant_id=request.tenant_id,
        entity_id=request.legal_entity_id,
        payload={
            "buyer_organisation_id": request.buyer_organisation_id,
            "tenant_id": request.tenant_id,
            "legal_entity_id": request.legal_entity_id,
            "source_system": "ERP",
            "credit_status": request.credit_status,
            "payment_term_code": request.payment_term_code,
            "credit_limit_minor": request.credit_limit_minor,
            "currency_code": request.currency_code.upper(),
            "profile_reference": request.profile_reference,
            "business_partner_id": request.business_partner_id,
            "as_of": record.decided_at.isoformat(),
        },
    )
