"""GET /legal-entities/{legal_entity_id}/effective-finance-baseline and GET /finance-baselines/{baseline_id}
(contracts/erp/v1/openapi.yaml 1.3.0, getEffectiveFinanceBaseline / getFinanceBaseline).

Other engines REFER to a Finance-approved baseline version; the accounting configuration is ERP's and never leaves it. These
reads only resolve a reference: they never create, approve or infer a baseline, and disclose one accounting value, the
functional currency.

Both serve provisioning of a tenant that is not yet ACTIVE, so the caller is the provisioner under a TENANT_PROVISIONING
context (the server has already validated that purpose). The legal entity must belong to the provisioning that context is bound
to: Control Plane's ERP assignment for exactly that tenant, provisioning and legal entity is the authority, and a legal entity
it does not know is indistinguishable from one that does not exist (404).

Pure request -> (status, body) logic; server.py owns HTTP, authentication and the connection.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs

from application.problem import problem
from provisioning.control_plane_client import AssignmentNotEstablished, ControlPlaneUnavailable
from provisioning.cp_contract import AssignmentError
from provisioning.finance_baseline import BASELINE_DIGEST, BASELINE_ID, baseline_digest, resolution_of
from provisioning.finance_baseline_store import PostgresFinanceBaselineStore

FINANCE_BASELINE_MISMATCH = "FINANCE_BASELINE_MISMATCH"
FINANCE_BASELINE_NOT_USABLE = "FINANCE_BASELINE_NOT_USABLE"
RETRY_AFTER_SECONDS = "30"
_LEGAL_ENTITY = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_VERSION = re.compile(r"^[1-9][0-9]{0,8}$")


def in_provisioning(*, provisioning, tenant_id: str, context_authority, legal_entity_id: str) -> str:
    """Whether the legal entity belongs to the provisioning the context is bound to: "yes", "no" or "unavailable".

    Control Plane's assignment for this tenant, provisioning and legal entity is the authority. An assignment for another
    tenant or plan than the context's is "no", never a way to read across them."""
    if provisioning is None:
        return "unavailable"
    if context_authority is None:
        return "no"
    try:
        assignment = provisioning.control_plane.resolve_erp_assignment(
            tenant_id=tenant_id, tenant_provisioning_id=context_authority.tenant_provisioning_id, legal_entity_id=legal_entity_id)
    except (AssignmentNotEstablished, AssignmentError):
        return "no"
    except ControlPlaneUnavailable:
        return "unavailable"
    same_plan = (assignment.tenant_id, assignment.tenant_provisioning_id, assignment.plan_id, assignment.plan_version,
                 assignment.plan_digest, assignment.legal_entity_id) == (
        tenant_id, context_authority.tenant_provisioning_id, context_authority.plan_id, context_authority.plan_version,
        context_authority.plan_digest, legal_entity_id)
    return "yes" if same_plan else "no"


def _today(provisioning) -> date:
    now = provisioning.now() if provisioning is not None else datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).date()


def get_effective_finance_baseline(*, tenant_id, argument, query_string, connection, correlation_id, trace_id,
                                   context_authority=None, provisioning=None, **_) -> tuple[int, dict]:
    def bad(field, message):
        return problem("invalid_request", correlation_id=correlation_id, trace_id=trace_id,
                       errors=[{"code": "ERP_INVALID_PARAMETER", "message": message, "field": field}])

    if not (3 <= len(argument) <= 63 and _LEGAL_ENTITY.fullmatch(argument)):
        return bad("legal_entity_id", "must be a canonical legal entity identifier")
    query = parse_qs(query_string, keep_blank_values=True)
    for name in sorted(set(query) - {"effective_on", "context_id"}):
        return bad(name, "unknown query parameter")
    today = _today(provisioning)
    if "effective_on" in query:
        raw = query["effective_on"]
        if len(raw) != 1 or not _DATE.fullmatch(raw[0]):
            return bad("effective_on", "must be a calendar date (YYYY-MM-DD)")
        try:
            today = date.fromisoformat(raw[0])
        except ValueError:
            return bad("effective_on", "must be a calendar date (YYYY-MM-DD)")
    belongs = in_provisioning(provisioning=provisioning, tenant_id=tenant_id, context_authority=context_authority,
                              legal_entity_id=argument)
    if belongs == "unavailable":
        return _unavailable(correlation_id, trace_id)
    if belongs == "no":
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id)
    store = PostgresFinanceBaselineStore(connection)
    baseline = store.effective(argument, today)
    if baseline is None:
        # Nothing approved is in force: ERP never creates or infers one, and Control Plane must not provision this entity.
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id,
                       detail="no Finance-approved baseline is in force for the legal entity")
    return 200, resolution_of(baseline, store.status(baseline, today), _now(provisioning))


def get_finance_baseline(*, tenant_id, argument, query_string, connection, correlation_id, trace_id,
                         context_authority=None, provisioning=None, **_) -> tuple[int, dict]:
    def bad(field, message):
        return problem("invalid_request", correlation_id=correlation_id, trace_id=trace_id,
                       errors=[{"code": "ERP_INVALID_PARAMETER", "message": message, "field": field}])

    if not (6 <= len(argument) <= 63 and BASELINE_ID.fullmatch(argument)):
        return bad("baseline_id", "must be a Finance baseline identifier")
    query = parse_qs(query_string, keep_blank_values=True)
    for name in sorted(set(query) - {"version", "digest", "context_id"}):
        return bad(name, "unknown query parameter")
    # Exact resolution needs both: a read that could mean "the latest" is not an exact reference.
    versions, digests = query.get("version", []), query.get("digest", [])
    if len(versions) != 1 or not _VERSION.fullmatch(versions[0]):
        return bad("version", "is required and must be an integer >= 1")
    if len(digests) != 1 or not BASELINE_DIGEST.fullmatch(digests[0]):
        return bad("digest", "is required and must be a sha256 digest")
    version, digest = int(versions[0]), digests[0]
    store = PostgresFinanceBaselineStore(connection)
    legal_entity_id = store.legal_entity_of(argument)
    if legal_entity_id is None:
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id)
    belongs = in_provisioning(provisioning=provisioning, tenant_id=tenant_id, context_authority=context_authority,
                              legal_entity_id=legal_entity_id)
    if belongs == "unavailable":
        return _unavailable(correlation_id, trace_id)
    if belongs == "no":
        # Indistinguishable from an unknown baseline.
        return problem("not_found", correlation_id=correlation_id, trace_id=trace_id)
    baseline = store.get(legal_entity_id, version)
    if baseline is None or baseline_digest(baseline) != digest:
        return problem("conflict", correlation_id=correlation_id, trace_id=trace_id, code=FINANCE_BASELINE_MISMATCH,
                       detail="the baseline has no such version, or that version's digest differs")
    return 200, resolution_of(baseline, store.status(baseline, _today(provisioning)), _now(provisioning))


def _now(provisioning) -> datetime:
    return provisioning.now() if provisioning is not None else datetime.now(timezone.utc)


def _unavailable(correlation_id, trace_id):
    status, body = problem("unavailable", correlation_id=correlation_id, trace_id=trace_id,
                           detail="Control Plane's assignment could not be read; nothing was resolved")
    return status, body, {"Retry-After": RETRY_AFTER_SECONDS}
