"""The invoice and payment accounting outcomes ERP announces (``invoice.changed``, ``payment.accounting-changed``; ADR-ERP-016).

Both events are built only from facts ERP observed: the document number, total, currency and paid state are read back from the engine
after the native process ran, never taken from the request and never invented. Where the contract makes a member optional and ERP does
not hold the fact (an invoice's due date and outstanding amount are computed by the engine, not stored on the invoice), it is left out.

A change is announced once. ``DocumentOutcomeStore.advance`` moves a document's revision only when its status or the facts that matter
changed, so a retried request announces nothing twice; the event id and idempotency key are derived from (tenant, document, revision).

Pure and database-free: the rules are tested without Postgres; ``order_to_cash.outcome_store`` persists the revisions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from events.cloudevent import CloudEvent, new_event

INVOICE_EVENT = "com.baobab-platform.erp.invoice.changed.v1"
PAYMENT_EVENT = "com.baobab-platform.erp.payment.accounting-changed.v1"
_NAMESPACE = uuid.UUID("0a6e1d52-8f4b-5e07-9c1a-7b3d2e9f4a60")
_COMPLETED = frozenset({"CO", "CL"})  # iDempiere DocStatus: Completed, Closed


class AccountingFactError(Exception):
    """A fact an outcome needs is missing or inconsistent in the engine. No event is built from a guess."""


@dataclass(frozen=True, slots=True)
class Money:
    amount: str
    currency: str

    def contract(self) -> dict:
        return {"amount": self.amount, "currency": self.currency}


@dataclass(frozen=True, slots=True)
class InvoiceFacts:
    number: str
    total: Money
    completed: bool
    paid: bool


@dataclass(frozen=True, slots=True)
class PaymentFacts:
    amount: Money
    completed: bool

    @property
    def payment_amount_text(self) -> str:
        return self.amount.amount


@dataclass(frozen=True, slots=True)
class Advanced:
    """A document's revision after ``advance``; ``changed`` is False when nothing observed differs from the last revision."""

    revision: int
    first_seen_at: datetime
    changed: bool


class DocumentOutcomeStore(Protocol):
    def advance(self, *, tenant_id: str, document_type: str, document_id: str, status: str, detail: dict,
                now: datetime) -> Advanced: ...


class Engine(Protocol):
    def get_record(self, table: str, record_id: int) -> dict[str, Any]: ...


# -- reading facts from the engine -----------------------------------------------------------------------------------------------

def _code(value: Any) -> str | None:
    """A column that is a list or a reference comes back as ``{"id": ...}``; a plain column as its value."""
    if isinstance(value, dict):
        value = value.get("id")
    return None if value is None else str(value)


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "y", "yes", "1")


def _money(engine: Engine, amount: Any, currency_ref: Any, what: str) -> Money:
    currency_id = _code(currency_ref)
    if currency_id is None or not currency_id.isdigit():
        raise AccountingFactError(f"{what} has no currency")
    currency = engine.get_record("C_Currency", int(currency_id))
    iso = currency.get("ISO_Code")
    if not isinstance(iso, str) or len(iso) != 3 or not iso.isupper():
        raise AccountingFactError(f"{what}'s currency has no ISO code")
    try:
        value = Decimal(str(amount))
        places = int(currency.get("StdPrecision", 2))
        if not value.is_finite() or value < 0 or not 0 <= places <= 6:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise AccountingFactError(f"{what} has no valid amount") from None
    return Money(format(value.quantize(Decimal(1).scaleb(-places)), "f"), iso)


def read_invoice(engine: Engine, native_id: int) -> InvoiceFacts:
    record = engine.get_record("C_Invoice", native_id)
    number = record.get("DocumentNo")
    if not isinstance(number, str) or not number.strip() or len(number) > 96:
        raise AccountingFactError("the invoice has no document number")
    return InvoiceFacts(number, _money(engine, record.get("GrandTotal"), record.get("C_Currency_ID"), "the invoice"),
                        _code(record.get("DocStatus")) in _COMPLETED, _flag(record.get("IsPaid", False)))


def read_payment(engine: Engine, native_id: int) -> PaymentFacts:
    record = engine.get_record("C_Payment", native_id)
    return PaymentFacts(_money(engine, record.get("PayAmt"), record.get("C_Currency_ID"), "the payment"),
                        _code(record.get("DocStatus")) in _COMPLETED)


# -- what the facts establish ----------------------------------------------------------------------------------------------------

def invoice_status(facts: InvoiceFacts, *, allocated: bool = False) -> str:
    """posted, or paid / partially_paid once a payment was allocated against it. An invoice the engine has not completed is not
    announced: ERP reports what it observed, and it observed no posting."""
    if not facts.completed:
        raise AccountingFactError("the invoice is not completed in the engine")
    if facts.paid:
        return "paid"
    return "partially_paid" if allocated else "posted"


def payment_status(facts: PaymentFacts, *, allocated_amount: str | None = None) -> str:
    """posted once the payment is completed; allocated or partially_allocated after an allocation, by comparing the amount allocated
    with the payment's own amount."""
    if not facts.completed:
        raise AccountingFactError("the payment is not completed in the engine")
    if allocated_amount is None:
        return "posted"
    try:
        allocated = Decimal(allocated_amount)
    except InvalidOperation:
        raise AccountingFactError("the allocated amount is not a number") from None
    if not allocated.is_finite() or allocated <= 0:
        raise AccountingFactError("the allocated amount must be positive")
    return "allocated" if allocated >= Decimal(facts.payment_amount_text) else "partially_allocated"


# -- the events ------------------------------------------------------------------------------------------------------------------

def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _correlation(tenant_id: str, document_id: str, supplied: str | None) -> str:
    try:
        return str(uuid.UUID(str(supplied)))
    except (ValueError, TypeError):
        return str(uuid.uuid5(_NAMESPACE, f"correlation|{tenant_id}|{document_id}"))


def invoice_changed_event(*, tenant_id: str, legal_entity_id: str, invoice_id: str, commerce_order_id: str, facts: InvoiceFacts,
                          status: str, issued_at: datetime, revision: int, now: datetime, correlation_id: str | None) -> CloudEvent:
    data = {"legal_entity_id": legal_entity_id, "invoice_id": invoice_id, "invoice_number": facts.number,
            "commerce_order_id": commerce_order_id, "status": status, "total": facts.total.contract(),
            "issued_at": _stamp(issued_at), "revision": revision}
    event = new_event(
        type=INVOICE_EVENT, subject=f"invoice:{invoice_id}", correlation_id=_correlation(tenant_id, commerce_order_id, correlation_id),
        data=data, tenant_id=tenant_id, time=now, idempotency_key=f"erp-invoice-{invoice_id}-r{revision}")
    return replace(event, id=str(uuid.uuid5(_NAMESPACE, f"invoice|{tenant_id}|{invoice_id}|{revision}")))


def payment_accounting_event(*, tenant_id: str, legal_entity_id: str, payment_capture_id: str, erp_payment_id: str,
                             invoice_id: str | None, facts: PaymentFacts, status: str, revision: int, now: datetime,
                             correlation_id: str | None) -> CloudEvent:
    data = {"legal_entity_id": legal_entity_id, "payment_capture_id": payment_capture_id, "erp_payment_id": erp_payment_id,
            "status": status, "amount": facts.amount.contract(), "accounted_at": _stamp(now), "revision": revision}
    if invoice_id is not None:
        data["invoice_id"] = invoice_id
    event = new_event(
        type=PAYMENT_EVENT, subject=f"payment:{payment_capture_id}",
        correlation_id=_correlation(tenant_id, payment_capture_id, correlation_id), data=data, tenant_id=tenant_id, time=now,
        idempotency_key=f"erp-payment-{payment_capture_id}-r{revision}")
    return replace(event, id=str(uuid.uuid5(_NAMESPACE, f"payment|{tenant_id}|{payment_capture_id}|{revision}")))
