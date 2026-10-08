"""Executes a claimed ``trade.customer.projected`` inbox row: the path from an accepted customer event to a business partner in the engine
and the master-data mapping that order execution resolves its customer through (ADR-ERP-006, ADR-ERP-007, ADR-ERP-014).

Until this existed an order was blocked as ``CUSTOMER_UNMAPPED`` unless someone had written the mapping by hand: the event was received and
nothing then acted on it.

What is guaranteed, and how:

* **One business partner per (tenant, legal entity, Trade customer).** A replay, a redelivered version, a second worker and a restart after
  an uncertain outcome are collapsed by the mapping (primary key engine instance + legal entity + kind + canonical id), a session advisory
  lock per customer held while the engine is touched, and a marker written into the created record.
* **An uncertain outcome is not repeated.** Creating the engine record and committing ERP's rows cannot be one transaction. If a worker
  dies in between, the next attempt finds the record by its marker (never by name) and adopts it. More than one match is a dead letter.
* **Versions only move forward.** An older version is ignored (``STALE_VERSION``), the same version again is a no-op, and the same version
  with different content is a producer error (``VERSION_CONFLICT``), never applied. A newer version updates the partner in place.
* **ERP's rows commit together or not at all**: the mapping and the inbox outcome are one transaction, fenced on the inbox lease.
* **Nothing is fabricated.** No tenant placement, no engine credentials, or no default business-partner group blocks the event with a named
  code; it is retried slowly until a horizon, then dead-lettered.
* **A customer is never deleted.** A suspended or closed customer becomes an inactive partner; orders and history keep referring to it.

Outcome codes are fixed strings and never carry payload content. This has run against a fake engine, not a live iDempiere: ``Description``
as the marker column, the default ``C_BP_Group`` lookup and the ``IsCustomer`` / ``IsActive`` fields are what a live run must confirm.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Protocol

import psycopg

from customers.payload import CustomerProjection, PayloadError, marker, parse_customer_projected
from inbox.execution_support import (AdvisoryLock, EngineOrgMismatch, PostgresMasterData, blocked, dead, engine_errors, settle,
                                     utc_now)
from inbox.postgres_queue import Claim, PostgresInboxQueue
from integration.idempiere_client import Eq, IdempiereApiError
from order_to_cash.execution_policy import CONTENTION_DELAY_SECONDS, CUSTOMER_KIND, Outcome
from provisioning.master_data_mapping import PostgresMasterDataMappingStore

CUSTOMER_PROJECTED = "com.baobab-platform.trade.customer.projected.v1"
SETTLED_IN_ATTEMPT = frozenset({"CREATED", "ADOPTED_NATIVE_PARTNER", "UPDATED"})
TABLE = "C_BPartner"


class IdempierePartners(Protocol):
    def get_record(self, table: str, record_id: int) -> dict: ...

    def query(self, table: str, conditions, select) -> list[dict]: ...

    def create_record(self, table: str, fields: dict) -> int: ...

    def update_record(self, table: str, record_id: int, fields: dict) -> None: ...


def _record_id(row: dict, table: str) -> int:
    return int(row["id"] if "id" in row else row[f"{table}_ID"])


def _find_marked(engine: IdempierePartners, text: str) -> int | None:
    rows = engine.query(TABLE, [Eq("Description", text)], [f"{TABLE}_ID"])
    if len(rows) > 1:
        raise dead("DUPLICATE_NATIVE_PARTNERS", f"{len(rows)} engine partners carry the customer's marker")
    return _record_id(rows[0], TABLE) if rows else None


def _default_group(engine: IdempierePartners) -> int:
    """C_BPartner requires a business-partner group. Each client has one flagged as the default; ERP uses it rather than inventing a
    mapping. No default (or several) is a configuration an operator fixes, so the event blocks."""
    rows = engine.query("C_BP_Group", [Eq("IsDefault", True)], ["C_BP_Group_ID"])
    if len(rows) != 1:
        raise blocked("BP_GROUP_UNAVAILABLE", f"{len(rows)} default business-partner groups in the tenant's client (exactly one is needed)")
    return _record_id(rows[0], "C_BP_Group")


def _update_fields(customer: CustomerProjection) -> dict:
    return {"Name": customer.display_name, "IsActive": customer.active}


def _execute(claim: Claim, connection: psycopg.Connection, queue: PostgresInboxQueue,
             engine_for: Callable[[int, int], IdempierePartners | None]) -> Outcome:
    try:
        customer = parse_customer_projected(claim.data)
    except PayloadError as exc:
        raise dead("PAYLOAD_INVALID", str(exc)) from None
    if not claim.tenant_id:
        raise dead("TENANT_MISSING", "a tenant-scoped customer event carries no tenant")

    masters = PostgresMasterData(connection)
    target = masters.target(claim.tenant_id, customer.legal_entity_id)
    if target is None or target.engine_instance_id is None:
        raise blocked("TENANT_UNMAPPED", "no active engine placement for the tenant and legal entity")

    key = f"baobab.customer|{claim.tenant_id}|{customer.legal_entity_id}|{customer.customer_id}"
    with AdvisoryLock(connection, key) as lock:
        if not lock.held:
            return Outcome("retry", "CUSTOMER_CONTENDED", delay_seconds=CONTENTION_DELAY_SECONDS, refund_attempt=True)
        mappings = PostgresMasterDataMappingStore(connection)
        digest = customer.digest()
        mapped = mappings.get(engine_instance_id=target.engine_instance_id, legal_entity_id=customer.legal_entity_id,
                              kind=CUSTOMER_KIND, canonical_id=customer.customer_id)
        connection.commit()
        if mapped is not None:
            native_id, mapped_digest, mapped_version = mapped
            if customer.customer_version < int(mapped_version):
                return Outcome("processed", "STALE_VERSION")
            if customer.customer_version == int(mapped_version):
                if digest == mapped_digest:
                    return Outcome("processed", "ALREADY_PROJECTED")
                raise dead("VERSION_CONFLICT", "the same customer version arrived with different content")

        try:
            engine = engine_for(target.ad_client_id, target.ad_org_id)
        except EngineOrgMismatch:
            raise blocked("ENGINE_ORG_MISMATCH", "the engine credentials are for another AD_Org than the tenant's mapping") from None
        if engine is None:
            raise blocked("ENGINE_UNCONFIGURED", "no engine credentials for the tenant's AD_Client")

        with engine_errors():
            if mapped is not None:
                try:
                    engine.get_record(TABLE, native_id)
                except IdempiereApiError as exc:
                    if exc.status == 404:  # mapped, but gone from the engine: retrying cannot bring it back
                        raise dead("NATIVE_PARTNER_MISSING", "the mapped engine partner no longer exists") from None
                    raise
                engine.update_record(TABLE, native_id, _update_fields(customer))
                code = "UPDATED"
            else:
                text = marker(claim.tenant_id, customer)
                adopted = _find_marked(engine, text)
                if adopted is not None:
                    native_id, code = adopted, "ADOPTED_NATIVE_PARTNER"
                    engine.update_record(TABLE, native_id, _update_fields(customer))  # bring it to this version
                else:
                    native_id = engine.create_record(TABLE, {
                        **_update_fields(customer), "Value": customer.customer_id, "IsCustomer": True,
                        "C_BP_Group_ID": _default_group(engine), "Description": text})
                    code = "CREATED"

        # one transaction: the mapping order execution resolves the customer through, and the inbox outcome
        try:
            mappings.put(engine_instance_id=target.engine_instance_id, legal_entity_id=customer.legal_entity_id, kind=CUSTOMER_KIND,
                         canonical_id=customer.customer_id, native_id=native_id, desired_digest=digest,
                         source_version=str(customer.customer_version), commit=False)
            queue.processed(claim, code)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        return Outcome("processed", code)


def run_claim(claim: Claim, connection: psycopg.Connection, queue: PostgresInboxQueue,
              engine_for: Callable[[int, int], IdempierePartners | None], *, now: Callable[[], datetime] = utc_now) -> Outcome:
    """Executes one claimed row and settles it (see ``inbox.execution_support.settle``)."""
    return settle(claim, connection, queue, lambda: _execute(claim, connection, queue, engine_for),
                  settled_in_attempt=SETTLED_IN_ATTEMPT, now=now)
