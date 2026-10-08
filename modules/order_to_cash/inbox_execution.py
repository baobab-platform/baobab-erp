"""Executes a claimed ``trade.order.placed`` inbox row: the path from an accepted order event to a sales order in the engine,
the ERP-owned consequence record and its registered ``order.consequence-changed`` event (ADR-ERP-006, ADR-ERP-016).

What is guaranteed, and how:

* **One sales order per (tenant, Trade order).** A replayed event, a second event for the same order and a second worker are
  all collapsed by three things: the consequence record / ``baobab.order_execution`` row (primary key tenant + order), a
  session advisory lock per order held while the engine is touched, and the engine's own POReference.
* **An uncertain outcome is not repeated.** Creating the engine order and committing ERP's rows cannot be one transaction. If a
  worker dies in between, the next attempt finds the engine order by its POReference and adopts it instead of creating another.
  More than one match is not resolved by picking one; it is a dead letter for an operator.
* **ERP's rows commit together or not at all**: the consequence record, the order link, the outbox event and the inbox
  outcome are one transaction, fenced on the inbox lease. A worker that lost its lease rolls all of it back.
* **Nothing is fabricated.** A customer, product or tenant with no mapping blocks the event with a named code; it is retried
  slowly (a mapping can appear later) until a horizon, then dead-lettered.

Outcome codes are fixed strings and never carry payload content. Like the rest of ``integration/idempiere_client`` this has run
against a fake engine, not a live iDempiere; ``POReference`` as the lookup key is among the things a live run must confirm.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import psycopg

from inbox.postgres_queue import Claim, LeaseLostError, PostgresInboxQueue
from integration.idempiere_client import Eq, IdempiereApiError, IdempiereClientError
from order_to_cash.consequence_events import consequence_changed_event
from order_to_cash.consequence_store import PostgresOrderConsequenceStore
from order_to_cash.execution_policy import (CONTENTION_DELAY_SECONDS, CUSTOMER_KIND, PRODUCT_KIND, Outcome, erp_order_id,
                                            failure_outcome)
from order_to_cash.model import OrderLine
from order_to_cash.placed_order import PayloadError, PlacedOrder, parse_placed_order
from order_to_cash.service import sales_order_fields
from outbox.postgres_store import PostgresOutboxStore


class EngineOrgMismatch(Exception):
    """The engine credentials for the tenant's AD_Client are for a different AD_Org than the one its mapping names."""


class IdempiereOrders(Protocol):
    def get_record(self, table: str, record_id: int) -> dict: ...

    def query(self, table: str, conditions, select) -> list[dict]: ...

    def create_record(self, table: str, fields: dict) -> int: ...


class _Stop(Exception):
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome


def _dead(code: str, detail: str = "") -> _Stop:
    return _Stop(Outcome("dead_letter", code, detail))


def _blocked(code: str, detail: str = "") -> _Stop:
    return _Stop(Outcome("blocked", code, detail))


@dataclass(frozen=True, slots=True)
class Target:
    ad_client_id: int
    ad_org_id: int
    engine_instance_id: str | None


class PostgresOrderMasterData:
    """Explicit mappings only (ADR-ERP-007): a tenant's engine placement and the master-data mapping of a customer or product.
    Nothing is matched by name, code or position."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def target(self, tenant_id: str, legal_entity_id: str) -> Target | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT ad_client_id, ad_org_id, engine_instance_id FROM baobab.tenant_mapping "
                "WHERE tenant_id = %s AND entity_id = %s AND status = 'active'", (tenant_id, legal_entity_id))
            row = cursor.fetchone()
        return Target(int(row[0]), int(row[1]), row[2]) if row else None

    def native(self, engine_instance_id: str, legal_entity_id: str, kind: str, canonical_id: str) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT native_id FROM baobab.erp_master_data_mapping "
                "WHERE engine_instance_id = %s AND legal_entity_id = %s AND resource_kind = %s AND canonical_id = %s",
                (engine_instance_id, legal_entity_id, kind, canonical_id))
            row = cursor.fetchone()
        return int(row[0]) if row else None


class _OrderLock:
    """A session advisory lock on one (tenant, order). Session-level, so it survives the transaction boundaries inside the
    attempt and is released by the database if the worker's connection dies. Needs a direct (non-pooled) connection."""

    def __init__(self, connection: psycopg.Connection, tenant_id: str, commerce_order_id: str) -> None:
        self._connection, self._key = connection, f"baobab.order|{tenant_id}|{commerce_order_id}"
        self.held = False

    def __enter__(self) -> "_OrderLock":
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (self._key,))
            self.held = bool(cursor.fetchone()[0])
        self._connection.commit()
        return self

    def __exit__(self, *_exc) -> None:
        if self.held:
            self._connection.rollback()  # an aborted transaction could not run the unlock
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (self._key,))
            self._connection.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _execute(claim: Claim, connection: psycopg.Connection, queue: PostgresInboxQueue,
             engine_for: Callable[[int, int], IdempiereOrders | None], now: Callable[[], datetime]) -> Outcome:
    try:
        order = parse_placed_order(claim.data)
    except PayloadError as exc:
        raise _dead("PAYLOAD_INVALID", str(exc)) from None
    if not claim.tenant_id:
        raise _dead("TENANT_MISSING", "a tenant-scoped order event carries no tenant")

    masters = PostgresOrderMasterData(connection)
    target = masters.target(claim.tenant_id, order.legal_entity_id)
    if target is None or target.engine_instance_id is None:
        raise _blocked("TENANT_UNMAPPED", "no active engine placement for the tenant and legal entity")

    with _OrderLock(connection, claim.tenant_id, order.commerce_order_id) as lock:
        if not lock.held:
            # another worker is on this very order; neither a failure nor an attempt
            return Outcome("retry", "ORDER_CONTENDED", delay_seconds=CONTENTION_DELAY_SECONDS, refund_attempt=True)
        consequences = PostgresOrderConsequenceStore(connection)
        known = consequences.get(claim.tenant_id, order.commerce_order_id)
        connection.commit()
        if known is not None:
            if order.order_version == known.order_version:
                return Outcome("processed", "ALREADY_EXECUTED")
            if order.order_version < known.order_version:
                return Outcome("processed", "STALE_VERSION")
            raise _dead("AMENDMENT_UNSUPPORTED", "a later version of an executed order; amendment is not implemented")

        lines = _resolve_lines(masters, target, order)
        try:
            engine = engine_for(target.ad_client_id, target.ad_org_id)
        except EngineOrgMismatch:
            raise _blocked("ENGINE_ORG_MISMATCH", "the engine credentials are for another AD_Org than the tenant's mapping") from None
        if engine is None:
            raise _blocked("ENGINE_UNCONFIGURED", "no engine credentials for the tenant's AD_Client")
        customer = masters.native(target.engine_instance_id, order.legal_entity_id, CUSTOMER_KIND, order.customer_id)
        if customer is None:
            raise _blocked("CUSTOMER_UNMAPPED", "the order's customer has no master-data mapping")

        native_id, adopted = _find_or_create(engine, order, customer, lines)

        # one transaction: consequence record, order link, announcing event, inbox outcome
        try:
            record = consequences.open_order(
                tenant_id=claim.tenant_id, legal_entity_id=order.legal_entity_id,
                commerce_order_id=order.commerce_order_id, order_version=order.order_version,
                erp_order_id=erp_order_id(claim.tenant_id, order.commerce_order_id), now=now())
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO baobab.order_execution (tenant_id, commerce_order_id, legal_entity_id, order_version, "
                    "erp_order_id, native_id, source_event_id, adopted) VALUES (%s,%s,%s,%s,%s,%s,%s::uuid,%s)",
                    (claim.tenant_id, order.commerce_order_id, order.legal_entity_id, order.order_version,
                     record.erp_order_id, native_id, claim.event_id, adopted))
            PostgresOutboxStore(connection).record_event(consequence_changed_event(record, claim.correlation_id))
            queue.processed(claim, "ADOPTED_NATIVE_ORDER" if adopted else "EXECUTED")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        return Outcome("processed", "ADOPTED_NATIVE_ORDER" if adopted else "EXECUTED")


def _resolve_lines(masters: PostgresOrderMasterData, target: Target, order: PlacedOrder) -> tuple[OrderLine, ...]:
    missing, lines = [], []
    for line in order.lines:
        product = masters.native(target.engine_instance_id, order.legal_entity_id, PRODUCT_KIND, line.sku_id)
        if product is None:
            missing.append(line.line_id)
            continue
        lines.append(OrderLine(product_canonical_id=str(product), quantity=line.quantity, unit_price=line.unit_price))
    if missing:
        raise _blocked("PRODUCT_UNMAPPED", f"{len(missing)} line(s) have no product mapping: " + ", ".join(missing[:10]))
    return tuple(lines)


def _reference(value, what: str) -> int:
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise IdempiereClientError(f"{what} is not a record reference")
    return int(value)


def _verify_units(engine: IdempiereOrders, order: PlacedOrder, lines: tuple[OrderLine, ...]) -> None:
    """The order line sends a bare quantity, which the engine reads in the product's own unit of measure. So the canonical unit
    must be that unit's X12 code; a different one (12 KG for a product sold in EA) would silently order a different quantity and
    is refused instead. There is no unit conversion here."""
    codes: dict[str, str] = {}
    wrong = []
    for placed, native in zip(order.lines, lines):
        if native.product_canonical_id not in codes:
            product = engine.get_record("M_Product", int(native.product_canonical_id))
            uom = engine.get_record("C_UOM", _reference(product.get("C_UOM_ID"), "C_UOM_ID"))
            codes[native.product_canonical_id] = str(uom.get("X12DE355"))
        if codes[native.product_canonical_id] != placed.unit:
            wrong.append(placed.line_id)
    if wrong:
        raise _dead("UNIT_MISMATCH", "line(s) in a unit other than the product's own: " + ", ".join(wrong[:10]))


def _find_or_create(engine: IdempiereOrders, order: PlacedOrder, customer: int, lines: tuple[OrderLine, ...]
                    ) -> tuple[int, bool]:
    """The engine order for this Trade order: the one an earlier attempt already created, or a new one."""
    try:
        existing = engine.query("C_Order", [Eq("POReference", order.commerce_order_id)], ["C_Order_ID"])
        if len(existing) > 1:
            raise _dead("DUPLICATE_NATIVE_ORDERS", f"{len(existing)} engine orders carry the order's reference")
        if existing:
            return int(existing[0]["id"] if "id" in existing[0] else existing[0]["C_Order_ID"]), True
        _verify_units(engine, order, lines)
        return engine.create_record(
            "C_Order", sales_order_fields(customer, order.currency, lines, reference=order.commerce_order_id)), False
    except IdempiereApiError as exc:
        if exc.status in (400, 422):
            raise _dead("ENGINE_REJECTED", f"HTTP {exc.status}") from None
        raise _Stop(Outcome("retry", "ENGINE_UNAVAILABLE", f"HTTP {exc.status}")) from None
    except IdempiereClientError:
        raise _Stop(Outcome("retry", "ENGINE_UNAVAILABLE", "the engine could not be reached")) from None


def run_claim(claim: Claim, connection: psycopg.Connection, queue: PostgresInboxQueue,
              engine_for: Callable[[int, int], IdempiereOrders | None], *, now: Callable[[], datetime] = _now) -> Outcome:
    """Executes one claimed row and settles it. Never raises for an event-level failure; a lost lease or an unexpected error
    is reported as the outcome it is (a lost lease leaves the row to its new holder)."""
    try:
        try:
            outcome = _execute(claim, connection, queue, engine_for, now)
        except _Stop as stop:
            outcome = stop.outcome
        if outcome.status == "processed" and outcome.code in ("EXECUTED", "ADOPTED_NATIVE_ORDER"):
            return outcome  # settled inside the transaction that made it true
        outcome = failure_outcome(outcome, attempts=claim.attempts, received_at=claim.received_at, now=now())
        connection.rollback()
        if outcome.status == "processed":
            queue.processed(claim, outcome.code)
        else:
            queue.release(claim, status=outcome.status, outcome_code=outcome.code, error=outcome.detail,
                          next_attempt_at=(now() + timedelta(seconds=outcome.delay_seconds)
                                           if outcome.delay_seconds is not None else None),
                          refund_attempt=outcome.refund_attempt)
        connection.commit()
        return outcome
    except LeaseLostError:
        connection.rollback()
        return Outcome("retry", "LEASE_LOST", "another worker holds the row now")
    except Exception as exc:  # noqa: BLE001 - settle the row; the type name is the only thing recorded
        connection.rollback()
        outcome = failure_outcome(Outcome("retry", "UNEXPECTED_ERROR", type(exc).__name__), attempts=claim.attempts,
                                  received_at=claim.received_at, now=now())
        try:
            queue.release(claim, status=outcome.status, outcome_code=outcome.code, error=outcome.detail,
                          next_attempt_at=(now() + timedelta(seconds=outcome.delay_seconds)
                                           if outcome.delay_seconds is not None else None))
            connection.commit()
        except Exception:  # noqa: BLE001 - the lease will expire and the row will be re-claimed
            connection.rollback()
        return outcome
