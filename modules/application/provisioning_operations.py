"""POST /provisioning-operations and GET /provisioning-operations/{operation_id} (contracts/erp/v1/openapi.yaml).

ERP provisions only what two independent authorities agree on, and fails closed on any difference:

* the approved Control Plane plan, read through Control Plane's ERP assignment for each legal entity and compared member by
  member with the exact plan the request names (tenant, provisioning, plan id, version, digest, legal entity);
* the Finance-approved baseline in force for that legal entity (ADR-ERP-008).

The request's countries and currencies are intent, never authority. A command is accepted atomically: either every legal
entity is planned and recorded under one operation, or nothing is written. ``accepted`` means durably accepted and planned;
execution against iDempiere is a separate step (the operation's state advances as it runs), so 202 is never "provisioned".

Pure request -> (status, body, headers) logic; server.py owns HTTP, authentication and the connection.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

import psycopg

from application.finance_baselines import FINANCE_BASELINE_MISMATCH, FINANCE_BASELINE_NOT_USABLE
from application.problem import problem
from provisioning.authoritative_service import AuthoritativeProvisioningRequestFactory
from provisioning.command_events import state_document
from provisioning.command_store import CommandRecord, PlannedEntity, PostgresProvisioningCommandStore
from provisioning.control_plane_client import AssignmentNotEstablished, ControlPlaneUnavailable
from provisioning.cp_contract import AssignmentError, ControlPlaneAssignmentSource, CpErpAssignment, ErpMarketConfiguration
from provisioning.finance_baseline import EFFECTIVE, baseline_digest, baseline_id_for
from provisioning.finance_baseline_store import PostgresFinanceBaselineStore
from provisioning.legal_entity_policy import NativePlacementPolicy
from provisioning.operation_request import IDEMPOTENCY_KEY, ProvisioningCommand, RequestError, parse_command
from provisioning.planner import build_plan
from provisioning.validation import InvalidProvisioningRequestError

PLAN_AUTHORITY_MISMATCH = "PLAN_AUTHORITY_MISMATCH"
IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
MAX_BODY_BYTES = 256 * 1024
RETRY_AFTER_SECONDS = "30"


@dataclass(frozen=True, slots=True)
class ProvisioningDependencies:
    """What provisioning needs beyond the database. None of it comes from a request."""
    control_plane: ControlPlaneAssignmentSource
    native_placement: NativePlacementPolicy
    market_configuration: Mapping[str, ErpMarketConfiguration]
    target_environment: str
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class _ExactBaselines:
    """The Finance baseline versions the request referenced, already verified exactly, so the request built for each legal
    entity uses precisely those and never whatever ERP holds now."""

    def __init__(self, baselines: dict) -> None:
        self._baselines = baselines

    def effective(self, legal_entity_id, on):
        return self._baselines.get(legal_entity_id)


class _Fixed:
    """The assignment already read (and compared) for this legal entity, so the factory builds from exactly that."""

    def __init__(self, assignment: CpErpAssignment) -> None:
        self._assignment = assignment

    def resolve_erp_assignment(self, **_) -> CpErpAssignment:
        return self._assignment


def _state(record: CommandRecord) -> dict:
    return state_document(record)


def _differences(assignment: CpErpAssignment, command: ProvisioningCommand, legal_entity_id: str) -> list[str]:
    authority = command.authority
    pairs = (("tenant_id", assignment.tenant_id, command.tenant_id),
             ("tenant_provisioning_id", assignment.tenant_provisioning_id, authority.tenant_provisioning_id),
             ("plan_id", assignment.plan_id, authority.plan_id),
             ("plan_version", assignment.plan_version, authority.plan_version),
             ("plan_digest", assignment.plan_digest, authority.plan_digest),
             ("legal_entity_id", assignment.legal_entity_id, legal_entity_id))
    return [name for name, approved, requested in pairs if approved != requested]


def request_provisioning(*, tenant_id, principal, body: bytes, idempotency_key, connection: psycopg.Connection,
                         provisioning: ProvisioningDependencies | None, correlation_id: str, trace_id: str | None,
                         **_) -> tuple[int, dict, dict]:
    def fail(kind: str, detail: str | None = None, *, code: str | None = None, errors=None, headers=None):
        status, document = problem(kind, correlation_id=correlation_id, trace_id=trace_id, detail=detail, code=code,
                                   errors=errors)
        return status, document, headers or {}

    if not isinstance(idempotency_key, str) or not (16 <= len(idempotency_key) <= 128) \
            or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        return fail("invalid_request", "Idempotency-Key is required (16-128 characters of the canonical grammar)",
                    errors=[{"code": "ERP_INVALID_PARAMETER", "message": "missing or malformed", "field": "Idempotency-Key"}])
    if len(body) > MAX_BODY_BYTES:
        return fail("invalid_request", "the request body is too large")
    try:
        command = parse_command(json.loads(body))
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, RequestError):
            return fail("invalid_request", "the provisioning request is invalid",
                        errors=[{"code": "ERP_INVALID_PARAMETER", "message": message, "field": field}
                                for field, message in exc.errors])
        return fail("invalid_request", "the request body is not valid JSON")
    # The caller-bound CP-validated tenant is authority; the body may only agree with it.
    if command.tenant_id != tenant_id:
        return fail("forbidden", "tenant_id differs from the tenant of the validated context")
    # Only a well-formed, authorised request can learn that this deployment is not configured to provision.
    if provisioning is None:
        return fail("unavailable", "provisioning is not configured in this deployment", headers={"Retry-After": RETRY_AFTER_SECONDS})

    store = PostgresProvisioningCommandStore(connection)
    fingerprint = command.fingerprint(principal)
    store.lock_scope(tenant_id, idempotency_key)
    existing = store.find(tenant_id, idempotency_key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            return fail("conflict", "this Idempotency-Key was used for a different request", code=IDEMPOTENCY_KEY_REUSED)
        return 202, _state(existing), {}

    # 1. Control Plane's approved plan, legal entity by legal entity, compared with the exact plan the request names.
    assignments: dict[str, CpErpAssignment] = {}
    try:
        for legal_entity_id in sorted(command.legal_entity_ids):
            assignment = provisioning.control_plane.resolve_erp_assignment(
                tenant_id=tenant_id, tenant_provisioning_id=command.authority.tenant_provisioning_id,
                legal_entity_id=legal_entity_id)
            differences = _differences(assignment, command, legal_entity_id)
            if differences:
                return fail("conflict", f"the approved plan differs from the request for {legal_entity_id}: "
                            f"{', '.join(differences)}", code=PLAN_AUTHORITY_MISMATCH)
            assignments[legal_entity_id] = assignment
    except AssignmentNotEstablished as exc:
        return fail("conflict", f"Control Plane has no executable approved plan for {legal_entity_id}: "
                    f"{exc.code or exc.status}", code=PLAN_AUTHORITY_MISMATCH)
    except ControlPlaneUnavailable:
        return fail("unavailable", "Control Plane's assignment could not be read; nothing was provisioned",
                    headers={"Retry-After": RETRY_AFTER_SECONDS})
    except AssignmentError as exc:
        return fail("conflict", str(exc), code=PLAN_AUTHORITY_MISMATCH)

    # 2. The requested countries are intent: they must be exactly the markets the approved plan authorises.
    approved_markets = {market.market for a in assignments.values() for market in a.markets}
    if approved_markets != set(command.requested_countries):
        return fail("conflict", "requested_countries differ from the markets of the approved plan",
                    code=PLAN_AUTHORITY_MISMATCH)

    # 3. The Finance baselines. The request REFERS to one exact approved version per legal entity; ERP re-resolves each
    #    against its own store and never substitutes whatever it holds now.
    now = provisioning.now()
    baselines = PostgresFinanceBaselineStore(connection)
    referenced = {ref.legal_entity_id: ref for ref in command.finance_baselines}
    if set(referenced) != set(command.legal_entity_ids):
        return fail("conflict", "finance_baselines must reference exactly the requested legal entities, one each",
                    code=FINANCE_BASELINE_MISMATCH)
    exact = {}
    for legal_entity_id in sorted(referenced):
        ref = referenced[legal_entity_id]
        baseline = baselines.get(legal_entity_id, ref.version)
        if (baseline is None or baseline_id_for(legal_entity_id) != ref.baseline_id or baseline_digest(baseline) != ref.digest
                or baseline.effective_from.isoformat() != ref.effective_from):
            return fail("conflict", f"the Finance baseline reference for {legal_entity_id} is not what ERP holds",
                        code=FINANCE_BASELINE_MISMATCH)
        exact[legal_entity_id] = baseline
    for legal_entity_id, baseline in exact.items():
        if baselines.status(baseline, now.date()) != EFFECTIVE:
            return fail("conflict", f"the referenced Finance baseline of {legal_entity_id} is not effective",
                        code=FINANCE_BASELINE_NOT_USABLE)
    finance = _ExactBaselines(exact)

    # 4. Build each legal entity's request from the assignment plus ERP-owned inputs (Finance baseline, placement, markets).
    entities: list[PlannedEntity] = []
    functional_currencies: set[str] = set()
    for legal_entity_id, assignment in assignments.items():
        factory = AuthoritativeProvisioningRequestFactory(
            control_plane=_Fixed(assignment), native_placement=provisioning.native_placement,
            market_configuration=provisioning.market_configuration, finance=finance,
            target_environment=provisioning.target_environment)
        try:
            request = factory.build(tenant_id=tenant_id, tenant_provisioning_id=assignment.tenant_provisioning_id,
                                    legal_entity_id=legal_entity_id, on=now.date(), now=now)
            plan = build_plan(request)
        except (AssignmentError, InvalidProvisioningRequestError, NotImplementedError) as exc:
            return fail("conflict", f"{legal_entity_id} cannot be provisioned yet: {exc}")
        functional_currencies.add(request.accounting.functional_currency)
        entities.append(PlannedEntity(legal_entity_id, request, plan))
    if functional_currencies != set(command.functional_currencies):
        return fail("conflict", "functional_currencies differ from the Finance-approved baselines",
                    code=PLAN_AUTHORITY_MISMATCH)

    # 5. Accept atomically.
    try:
        record = store.accept(command=command, idempotency_key=idempotency_key, principal=principal,
                              fingerprint=fingerprint, entities=entities)
    except psycopg.errors.UniqueViolation:
        connection.rollback()
        return fail("conflict", "a legal entity of this request is already being provisioned under this approved plan "
                    "by another command")
    return 202, _state(record), {}


def get_provisioning_operation(*, tenant_id, argument, connection: psycopg.Connection, correlation_id: str,
                               trace_id: str | None, context_authority=None, **_) -> tuple[int, dict]:
    try:
        operation_id = str(uuid.UUID(argument))
    except (ValueError, TypeError, AttributeError):
        return problem("invalid_request", correlation_id=correlation_id, trace_id=trace_id,
                       detail="operation_id is not a UUID",
                       errors=[{"code": "ERP_INVALID_IDENTIFIER", "message": "must be a UUID", "field": "operation_id"}])
    record = PostgresProvisioningCommandStore(connection).get(tenant_id, operation_id)
    if record is None:
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id)
    # The tenant alone is not enough (Shared erp/v1 1.2.0): the context must be the provisioning context bound to the plan
    # this operation was accepted under. One bound to another provisioning or plan is the same indistinguishable rejection.
    if context_authority is None or (
            context_authority.tenant_provisioning_id, context_authority.plan_id, context_authority.plan_version,
            context_authority.plan_digest) != (record.tenant_provisioning_id, record.plan_id, record.plan_version,
                                              record.plan_digest):
        return problem("forbidden", correlation_id=correlation_id, trace_id=trace_id, code="ERP_CONTEXT_REJECTED")
    return 200, _state(record)
