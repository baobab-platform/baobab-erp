"""Sell-side order-to-cash command layer (ADR-ERP-016, ZuriBeans go-live Gate
ZB-16's "Sell side": Sales Order -> Shipment -> Invoice -> AR -> Receipt -> GL).

This is the "ERP Integration Consumer" ADR-ERP-016 SS17 describes: given an
already-resolved Baobab TenantScope, it creates and progresses the native
iDempiere documents a Commerce order triggers, through IdempiereClient (the
only supported way to reach a live iDempiere instance -- ADR-ERP-005), records
the resulting canonical<->native mapping the moment a document is created
(mapping.postgres_store.PostgresCanonicalMappingStore.create_mapping), and
records the resulting canonical fact on the transactional outbox in the same
database transaction as the mutation (ADR-ERP-004 SS44-51) -- callers are
responsible for that transaction boundary (open one connection, pass stores
built on it, commit once at the end), matching PostgresOutboxStore.record()'s
and PostgresCanonicalMappingStore.create_mapping()'s own documented contracts.

Every *_complete/_post/_allocate function invokes iDempiere's native process
for that action (IdempiereClient.execute_process) -- never a direct field
PATCH of DocStatus (ADR-ERP-004 SS26, INV-ERP-EXT-009/010) -- then emits
exactly one canonical erp.* event of its own. Six genuinely distinct facts are
kept separate, matching ADR-ERP-016 SS22 exactly: Commerce Order created !=
ERP Order accepted != ERP Order completed != Customer Invoice posted !=
Payment captured != Payment accounted. This module never re-publishes a
commerce.* event as its own fact (SS222-223, "no echo events") -- callers
translate an inbound commerce.order.placed.v1 into a create_sales_order call
themselves; this module only ever emits facts resulting from ERP's own
processing.

Code-complete against IdempiereClient's already-verified REST shape
(modules/integration/idempiere_client.py); not live-testable in this
environment since the iDempiere REST API plugin has never been installed
against a running instance (see that module's own docstring and
architecture/conformance.yaml against ADR-ERP-005).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from events.envelope import EventEnvelope
from mapping.model import MappingNotFoundError, NativeRecordRef
from order_to_cash.model import NativeDocumentRef, OrderLine, OrderToCashError, TenantScope

_EVENT_SCHEMA_VERSION = "1.0"
_EVENT_SOURCE = "baobab-erp"

# ADR-ERP-016 SS221's exact event-type list for the sell-side slice this
# module implements.
_EVENT_SALES_ORDER_ACCEPTED = "erp.sales-order.accepted.v1"
_EVENT_SHIPMENT_COMPLETED = "erp.goods-shipment.completed.v1"
_EVENT_INVOICE_POSTED = "erp.customer-invoice.posted.v1"
_EVENT_PAYMENT_COMPLETED = "erp.payment.completed.v1"
_EVENT_PAYMENT_ALLOCATED = "erp.payment.allocated.v1"

_TABLE_ORDER = "C_Order"
_TABLE_SHIPMENT = "M_InOut"
_TABLE_INVOICE = "C_Invoice"
_TABLE_PAYMENT = "C_Payment"


class IdempiereClient(Protocol):
    def create_record(self, table: str, fields: dict[str, Any]) -> int: ...

    def execute_process(self, process_id: int, parameters: dict[str, Any]) -> dict[str, Any]: ...


class MappingStore(Protocol):
    """The subset of PostgresCanonicalMappingStore this module needs -- both
    the read path modules/mapping already exposes and the write path
    (create_mapping) it added alongside this module, since creating the FIRST
    mapping for a record this same call just created is this module's job,
    not modules/mapping's (ADR-ERP-007 keeps resolution and origination
    separate)."""

    def find_native(self, tenant_id: str, canonical_type: str, canonical_id: str) -> NativeRecordRef | None: ...

    def create_mapping(
        self,
        tenant_id: str,
        legal_entity_id: str,
        canonical_type: str,
        canonical_id: str,
        native_table: str,
        native_id: int,
    ) -> None: ...


class OutboxStore(Protocol):
    def record(self, envelope: EventEnvelope) -> None: ...


@dataclass(frozen=True, slots=True)
class ProcessIds:
    """iDempiere native process IDs this deployment's document actions run
    through (ADR-ERP-004 SS26 / INV-ERP-EXT-009-010: complete/post a document
    by invoking its native process, never by PATCHing DocStatus directly).
    iDempiere assigns process IDs per installation -- these are deployment
    configuration, supplied by whoever provisions the instance, never guessed
    here."""

    complete_sales_order: int
    complete_shipment: int
    post_customer_invoice: int
    complete_payment: int
    allocate_payment: int


def _new_canonical_id() -> str:
    return str(uuid.uuid4())


def _envelope(
    event_type: str, scope: TenantScope, correlation_id: str, payload: dict[str, Any]
) -> EventEnvelope:
    return EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        schema_version=_EVENT_SCHEMA_VERSION,
        occurred_at=datetime.now(timezone.utc),
        source=_EVENT_SOURCE,
        correlation_id=correlation_id,
        tenant_id=scope.tenant_id,
        entity_id=scope.legal_entity_id,
        payload=payload,
    )


def _create_and_map(
    *,
    scope: TenantScope,
    canonical_type: str,
    canonical_id: str,
    native_table: str,
    fields: dict[str, Any],
    idempiere: IdempiereClient,
    mappings: MappingStore,
) -> NativeDocumentRef:
    native_id = idempiere.create_record(native_table, fields)
    mappings.create_mapping(
        scope.tenant_id, scope.legal_entity_id, canonical_type, canonical_id, native_table, native_id
    )
    return NativeDocumentRef(canonical_id=canonical_id, table=native_table, native_id=native_id)


def _resolve_native(
    *, scope: TenantScope, canonical_type: str, canonical_id: str, expected_table: str, mappings: MappingStore
) -> int:
    ref = mappings.find_native(scope.tenant_id, canonical_type, canonical_id)
    if ref is None:
        raise MappingNotFoundError(
            f"No active mapping for tenant_id={scope.tenant_id!r} canonical_type={canonical_type!r} "
            f"canonical_id={canonical_id!r}"
        )
    if ref.table != expected_table:
        raise OrderToCashError(
            f"canonical_id={canonical_id!r} maps to {ref.table}, not {expected_table} "
            "-- wrong lifecycle stage for this operation"
        )
    return ref.record_id


# --- Sales Order --------------------------------------------------------


def create_sales_order(
    *,
    scope: TenantScope,
    commerce_order_canonical_id: str,
    business_partner_native_id: int,
    document_currency: str,
    lines: tuple[OrderLine, ...],
    idempiere: IdempiereClient,
    mappings: MappingStore,
) -> NativeDocumentRef:
    """Creates a draft C_Order. Drafted, not yet accepted -- creation alone is
    not one of ADR-ERP-016 SS22's six distinct facts, so no event is emitted
    here; complete_sales_order emits erp.sales-order.accepted.v1 once the
    native process actually accepts it. business_partner_native_id must
    already be resolved (by the caller, via mapping.resolver.resolve_to_native
    against the commerce order's business-partner canonical id) -- this
    function never resolves Party/Product mappings itself, matching
    ADR-ERP-016 SS32-33/INV-ERP-O2C-013-014: a missing mapping fails the
    integration, it is never guessed from a SKU or display name."""
    if not lines:
        raise OrderToCashError("A sales order requires at least one order line")
    fields = {
        "C_BPartner_ID": business_partner_native_id,
        "CurrencyISO": document_currency,
        "OrderLines": [
            {"M_Product_ID": line.product_canonical_id, "QtyOrdered": line.quantity, "PriceEntered": line.unit_price}
            for line in lines
        ],
    }
    return _create_and_map(
        scope=scope,
        canonical_type="CommerceOrder",
        canonical_id=commerce_order_canonical_id,
        native_table=_TABLE_ORDER,
        fields=fields,
        idempiere=idempiere,
        mappings=mappings,
    )


def complete_sales_order(
    *,
    scope: TenantScope,
    commerce_order_canonical_id: str,
    correlation_id: str,
    process_ids: ProcessIds,
    idempiere: IdempiereClient,
    mappings: MappingStore,
    outbox: OutboxStore,
) -> None:
    native_id = _resolve_native(
        scope=scope,
        canonical_type="CommerceOrder",
        canonical_id=commerce_order_canonical_id,
        expected_table=_TABLE_ORDER,
        mappings=mappings,
    )
    idempiere.execute_process(process_ids.complete_sales_order, {"C_Order_ID": native_id, "DocAction": "CO"})
    outbox.record(
        _envelope(
            _EVENT_SALES_ORDER_ACCEPTED,
            scope,
            correlation_id,
            {"commerce_order_id": commerce_order_canonical_id, "erp_order_native_id": native_id},
        )
    )


# --- Shipment ------------------------------------------------------------


def create_shipment(
    *,
    scope: TenantScope,
    shipment_canonical_id: str,
    commerce_order_canonical_id: str,
    idempiere: IdempiereClient,
    mappings: MappingStore,
) -> NativeDocumentRef:
    order_native_id = _resolve_native(
        scope=scope,
        canonical_type="CommerceOrder",
        canonical_id=commerce_order_canonical_id,
        expected_table=_TABLE_ORDER,
        mappings=mappings,
    )
    fields = {"C_Order_ID": order_native_id}
    return _create_and_map(
        scope=scope,
        canonical_type="GoodsShipment",
        canonical_id=shipment_canonical_id,
        native_table=_TABLE_SHIPMENT,
        fields=fields,
        idempiere=idempiere,
        mappings=mappings,
    )


def complete_shipment(
    *,
    scope: TenantScope,
    shipment_canonical_id: str,
    correlation_id: str,
    process_ids: ProcessIds,
    idempiere: IdempiereClient,
    mappings: MappingStore,
    outbox: OutboxStore,
) -> None:
    native_id = _resolve_native(
        scope=scope,
        canonical_type="GoodsShipment",
        canonical_id=shipment_canonical_id,
        expected_table=_TABLE_SHIPMENT,
        mappings=mappings,
    )
    idempiere.execute_process(process_ids.complete_shipment, {"M_InOut_ID": native_id, "DocAction": "CO"})
    outbox.record(
        _envelope(
            _EVENT_SHIPMENT_COMPLETED,
            scope,
            correlation_id,
            {"shipment_id": shipment_canonical_id, "erp_shipment_native_id": native_id},
        )
    )


# --- Customer Invoice ------------------------------------------------------


def create_customer_invoice(
    *,
    scope: TenantScope,
    commerce_order_canonical_id: str,
    idempiere: IdempiereClient,
    mappings: MappingStore,
) -> NativeDocumentRef:
    """Mints a new canonical id for the invoice rather than accepting one from
    the caller: per the erp_system_of_record contract (nabhold/shared,
    referenced in contracts.lock.yaml), ERP is the sole canonical owner of
    Invoice -- unlike CommerceOrder/GoodsShipment/Payment, no other engine has
    an earlier canonical fact to reuse here."""
    order_native_id = _resolve_native(
        scope=scope,
        canonical_type="CommerceOrder",
        canonical_id=commerce_order_canonical_id,
        expected_table=_TABLE_ORDER,
        mappings=mappings,
    )
    fields = {"C_Order_ID": order_native_id}
    return _create_and_map(
        scope=scope,
        canonical_type="CustomerInvoice",
        canonical_id=_new_canonical_id(),
        native_table=_TABLE_INVOICE,
        fields=fields,
        idempiere=idempiere,
        mappings=mappings,
    )


def post_customer_invoice(
    *,
    scope: TenantScope,
    invoice_canonical_id: str,
    correlation_id: str,
    process_ids: ProcessIds,
    idempiere: IdempiereClient,
    mappings: MappingStore,
    outbox: OutboxStore,
) -> None:
    """Posts the invoice: AR is created, revenue/tax accounting happens, and
    the document becomes immutable (ADR-ERP-008 SS58-62) -- corrections from
    here on are a credit/debit note, never a further edit of this document."""
    native_id = _resolve_native(
        scope=scope,
        canonical_type="CustomerInvoice",
        canonical_id=invoice_canonical_id,
        expected_table=_TABLE_INVOICE,
        mappings=mappings,
    )
    idempiere.execute_process(process_ids.post_customer_invoice, {"C_Invoice_ID": native_id, "DocAction": "CO"})
    outbox.record(
        _envelope(
            _EVENT_INVOICE_POSTED,
            scope,
            correlation_id,
            {"invoice_id": invoice_canonical_id, "erp_invoice_native_id": native_id},
        )
    )


# --- Payment ---------------------------------------------------------------


def create_payment(
    *,
    scope: TenantScope,
    payment_canonical_id: str,
    business_partner_native_id: int,
    amount: str,
    currency: str,
    idempiere: IdempiereClient,
    mappings: MappingStore,
) -> NativeDocumentRef:
    """Records the ERP-side accounting fact for a payment already captured by
    Medusa/a payment provider (ADR-ERP-016 SS67-77: capture and accounting are
    kept as separate entities on purpose -- this function is never the thing
    that actually moves money, only the thing that records that it moved)."""
    fields = {"C_BPartner_ID": business_partner_native_id, "PayAmt": amount, "CurrencyISO": currency}
    return _create_and_map(
        scope=scope,
        canonical_type="Payment",
        canonical_id=payment_canonical_id,
        native_table=_TABLE_PAYMENT,
        fields=fields,
        idempiere=idempiere,
        mappings=mappings,
    )


def complete_payment(
    *,
    scope: TenantScope,
    payment_canonical_id: str,
    correlation_id: str,
    process_ids: ProcessIds,
    idempiere: IdempiereClient,
    mappings: MappingStore,
    outbox: OutboxStore,
) -> None:
    native_id = _resolve_native(
        scope=scope,
        canonical_type="Payment",
        canonical_id=payment_canonical_id,
        expected_table=_TABLE_PAYMENT,
        mappings=mappings,
    )
    idempiere.execute_process(process_ids.complete_payment, {"C_Payment_ID": native_id, "DocAction": "CO"})
    outbox.record(
        _envelope(
            _EVENT_PAYMENT_COMPLETED,
            scope,
            correlation_id,
            {"payment_id": payment_canonical_id, "erp_payment_native_id": native_id},
        )
    )


def allocate_payment(
    *,
    scope: TenantScope,
    payment_canonical_id: str,
    invoice_canonical_id: str,
    amount: str,
    correlation_id: str,
    process_ids: ProcessIds,
    idempiere: IdempiereClient,
    mappings: MappingStore,
    outbox: OutboxStore,
) -> None:
    """Matches a completed Payment against a posted Customer Invoice --
    genuinely distinct from complete_payment per ADR-ERP-016 SS67-77: a
    payment can be completed (money accounted for) before it is known which
    invoice(s) it settles, e.g. a prepayment or an overpayment held on
    account."""
    payment_native_id = _resolve_native(
        scope=scope,
        canonical_type="Payment",
        canonical_id=payment_canonical_id,
        expected_table=_TABLE_PAYMENT,
        mappings=mappings,
    )
    invoice_native_id = _resolve_native(
        scope=scope,
        canonical_type="CustomerInvoice",
        canonical_id=invoice_canonical_id,
        expected_table=_TABLE_INVOICE,
        mappings=mappings,
    )
    idempiere.execute_process(
        process_ids.allocate_payment,
        {"C_Payment_ID": payment_native_id, "C_Invoice_ID": invoice_native_id, "Amount": amount},
    )
    outbox.record(
        _envelope(
            _EVENT_PAYMENT_ALLOCATED,
            scope,
            correlation_id,
            {
                "payment_id": payment_canonical_id,
                "invoice_id": invoice_canonical_id,
                "amount": amount,
            },
        )
    )
