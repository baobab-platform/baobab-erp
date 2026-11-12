"""Lossless Trade -> iDempiere recovery coordinates (ADR-ERP-016).

The full canonical order key stays in ERP's immutable intent. The JVM receives
its standard C_Order_UU UUID, never a truncated POReference. Reserving an
intent grants no native permission: current CP/documentary/company checks
still surround lookup, creation and adoption. This is a private idempotency
coordinate; it neither creates a CP Mapping nor replaces canonical identity.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
import uuid

from integration.idempiere_client import IdempiereClientError

PROFILE = "native-uuid-v1"
_active_reference: ContextVar["NativeOrderReference | None"] = ContextVar(
    "baobab_erp_order_native_reference", default=None)


def configured():
    value = os.environ.get("BAOBAB_ERP_ORDER_REFERENCE_PROFILE", "legacy-poreference")
    if value not in ("legacy-poreference", PROFILE):
        raise IdempiereClientError("NATIVE_REFERENCE_PROFILE_INVALID")
    return value == PROFILE


@dataclass(frozen=True, slots=True)
class NativeOrderReference:
    tenant_id: str
    legal_entity_id: str
    commerce_order_id: str
    engine_instance_id: str
    ad_client_id: int
    ad_org_id: int
    native_uuid: str
    attempted: bool


def reserve(connection, claim, order, target, *, require_existing=False):
    """Commit a recovery intent before any remote effect; requires the order lock.

    Each immutable scope/version/business digest must match on retry. A new
    event ID cannot redirect an existing intent to changed business facts.
    No native ID is asserted until the independently verified JVM effect.
    """
    digest = "sha256:" + hashlib.sha256(json.dumps(
        claim.data, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    with connection.cursor() as cursor:
        if not require_existing:
            cursor.execute("""INSERT INTO baobab.order_native_reference
                (tenant_id,legal_entity_id,commerce_order_id,engine_instance_id,
                 ad_client_id,ad_org_id,order_version,desired_digest,
                 first_source_event_id,native_uuid)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid,%s::uuid)
                ON CONFLICT (tenant_id,legal_entity_id,commerce_order_id) DO NOTHING""",
                (claim.tenant_id, order.legal_entity_id, order.commerce_order_id,
                 target.engine_instance_id, target.ad_client_id, target.ad_org_id,
                 order.order_version, digest, claim.event_id, str(uuid.uuid4())))
        cursor.execute("""SELECT engine_instance_id,ad_client_id,ad_org_id,
            order_version,desired_digest,native_uuid::text,creation_attempted_at
            FROM baobab.order_native_reference
            WHERE tenant_id=%s AND legal_entity_id=%s AND commerce_order_id=%s
            FOR UPDATE""", (claim.tenant_id, order.legal_entity_id, order.commerce_order_id))
        row = cursor.fetchone()
        if not row or row[:5] != (target.engine_instance_id, target.ad_client_id,
                                 target.ad_org_id, order.order_version, digest):
            raise IdempiereClientError("NATIVE_REFERENCE_SCOPE_OR_FACTS_CHANGED")
    # This intentional independent durable intent survives a lost remote result.
    # Consequence/execution/outbox/inbox settlement still commit together later.
    connection.commit()
    return NativeOrderReference(claim.tenant_id, order.legal_entity_id,
        order.commerce_order_id, target.engine_instance_id,
        target.ad_client_id, target.ad_org_id, row[5], row[6] is not None)


def mark_creation_attempt(connection, reference):
    with connection.cursor() as cursor:
        cursor.execute("""UPDATE baobab.order_native_reference
            SET creation_attempted_at=coalesce(creation_attempted_at,clock_timestamp())
            WHERE tenant_id=%s AND legal_entity_id=%s AND commerce_order_id=%s
              AND native_uuid=%s::uuid""", (reference.tenant_id,
                reference.legal_entity_id, reference.commerce_order_id, reference.native_uuid))
        if cursor.rowcount != 1:
            raise IdempiereClientError("NATIVE_REFERENCE_INTENT_MISSING")
    connection.commit()


def bind_native(connection, reference, native_id):
    """Settle the immutable native link WITH execution/consequence/outbox/inbox."""
    if type(native_id) is not int or not 0 < native_id <= 2_147_483_647:
        raise IdempiereClientError("NATIVE_REFERENCE_NATIVE_ID_INVALID")
    with connection.cursor() as cursor:
        cursor.execute("""UPDATE baobab.order_native_reference SET native_id=%s
            WHERE tenant_id=%s AND legal_entity_id=%s AND commerce_order_id=%s
              AND native_uuid=%s::uuid AND creation_attempted_at IS NOT NULL
              AND (native_id IS NULL OR native_id=%s)""", (native_id,
                reference.tenant_id, reference.legal_entity_id,
                reference.commerce_order_id, reference.native_uuid, native_id))
        if cursor.rowcount != 1:
            raise IdempiereClientError("NATIVE_REFERENCE_NATIVE_BINDING_CHANGED")


@contextmanager
def using_reference(reference):
    token = _active_reference.set(reference)
    try:
        yield
    finally:
        _active_reference.reset(token)


def matches_governed_reference(marker, body):
    reference = _active_reference.get()
    return bool(reference and marker and tuple(marker) == (
        reference.tenant_id, reference.legal_entity_id, "create_sales_order",
        reference.commerce_order_id, reference.ad_client_id, reference.ad_org_id)
        and body.get("C_Order_UU") == reference.native_uuid
        and "POReference" not in body)
