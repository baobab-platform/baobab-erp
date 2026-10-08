"""The pure rules of order-event execution: outcome shape, retry/block budgets and the deterministic ERP order id.

Kept free of database and engine imports so the rules are unit-tested without Postgres (``order_to_cash.inbox_execution`` applies
them)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

ORDER_PLACED = "com.baobab-platform.trade.order.placed.v1"
MAX_ATTEMPTS = 24
RETRY_BASE_SECONDS = 30
RETRY_CEILING_SECONDS = 3600
ALL_ORGANIZATIONS_AD_ORG_ID = 0  # a tenant mapping at AD_Org 0 spans every organisation of its AD_Client
CONTENTION_DELAY_SECONDS = 5
BLOCKED_DELAY_SECONDS = 900
BLOCKED_HORIZON = timedelta(hours=72)

_NAMESPACE = uuid.UUID("b0b2c7a1-3d6e-5c41-8f0a-6d1e9a4c2b77")

CUSTOMER_KIND = "business_partner"
PRODUCT_KIND = "product"


@dataclass(frozen=True, slots=True)
class Outcome:
    """How a claimed row ended. ``status`` is processed, retry, blocked or dead_letter; ``code`` is a fixed identifier."""

    status: str
    code: str
    detail: str = ""
    delay_seconds: int | None = None
    refund_attempt: bool = False


def erp_order_id(tenant_id: str, commerce_order_id: str) -> str:
    """The public ERP identifier of the order. Deterministic, so a retry after an uncertain outcome mints the same one."""
    return "erp_" + uuid.uuid5(_NAMESPACE, f"order|{tenant_id}|{commerce_order_id}").hex


def retry_delay_seconds(attempts: int) -> int:
    """30 s, 1 min, 2 min ... doubling to a 1 h ceiling reached at the 8th attempt; 24 attempts span roughly 17 hours."""
    return min(RETRY_BASE_SECONDS * 2 ** (attempts - 1), RETRY_CEILING_SECONDS)


def failure_outcome(outcome: Outcome, *, attempts: int, received_at: datetime, now: datetime) -> Outcome:
    """Applies the budgets: a retry past MAX_ATTEMPTS and a block past its horizon become dead letters."""
    if outcome.status == "retry" and attempts >= MAX_ATTEMPTS:
        return Outcome("dead_letter", "ATTEMPTS_EXHAUSTED", outcome.code)
    if outcome.status == "blocked" and now - received_at > BLOCKED_HORIZON:
        return Outcome("dead_letter", "BLOCKED_HORIZON_EXCEEDED", outcome.code)
    if outcome.status == "retry" and outcome.delay_seconds is None:
        return Outcome("retry", outcome.code, outcome.detail, retry_delay_seconds(attempts))
    if outcome.status == "blocked":
        return Outcome("blocked", outcome.code, outcome.detail, BLOCKED_DELAY_SECONDS)
    return outcome
