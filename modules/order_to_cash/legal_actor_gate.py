"""ADR-BCP-027 LA-05D: *opt-in* legal-responsibility PEP for iDempiere actions.

Do not infer invoice issuer/accounting actor from TenantScope.legal_entity_id,
AD_Client_ID, a historic DEFAULT or a parent/child corporate relationship.
Caller supplies the CP-issued RUNTIME PlatformContext handle and the operation's
independently resolved canonical expected legal actor; CP rechecks everything.
This seam MUST be installed at the live command path before production support.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Protocol, TypeVar

_T = TypeVar("_T")
_MAX_DECISION_AGE = timedelta(seconds=30)
_ALLOWED_ROLES = frozenset({"INVOICE_ISSUER", "ACCOUNTING_ENTITY", "CONTRACTING_PARTY"})


class LegalActorNotAuthorised(PermissionError):
    """No verified legal responsibility or provider readiness for this action."""


@dataclass(frozen=True, slots=True)
class LegalActorOperation:
    context_id: str  # CP-minted, canonical principal-owned RUNTIME context
    tenant_id: str
    operating_organisation_id: str
    expected_legal_entity_id: str  # verified operational target, not tenant DEFAULT
    role: str
    activity: str
    market: str
    capability: str
    operation_reference: str

    def validate(self) -> None:
        import re
        if not all((self.context_id, self.tenant_id, self.operating_organisation_id,
                    self.expected_legal_entity_id, self.activity, self.capability,
                    self.operation_reference)) or self.role not in _ALLOWED_ROLES or (
                        re.fullmatch(r"[A-Z]{2}", self.market) is None
                    ):
            raise LegalActorNotAuthorised("explicit scoped operation identity required")


class LegalActorAssessor(Protocol):
    def assess(self, request: Mapping[str, str]) -> Mapping[str, object]: ...


class LegalActorProviderReadiness(Protocol):
    def ensure_legal_actor_usable(self, operation: LegalActorOperation, mandate_id: str) -> None: ...


def assert_current_decision(
    operation: LegalActorOperation,
    response: Mapping[str, object],
    *,
    now: datetime,
) -> str:
    """Return a mandate identifier only after a strictly current CP decision."""
    operation.validate()
    if (response.get("context_id") != operation.context_id or
            response.get("operation_reference") != operation.operation_reference or
            response.get("provider_permissions_granted") is not False):
        raise LegalActorNotAuthorised("CP response is not this operation's decision")
    resolution = response.get("legal_actor_resolution")
    if not isinstance(resolution, dict) or resolution.get("outcome") != "AUTHORIZED":
        raise LegalActorNotAuthorised("current legal actor authority denied")
    if (resolution.get("responsible_legal_entity_id") != operation.expected_legal_entity_id or
            not isinstance(resolution.get("mandate_id"), str) or
            not resolution["mandate_id"] or
            not isinstance(resolution.get("evidence_references"), list) or
            not resolution["evidence_references"] or
            not all(isinstance(v, str) and v for v in resolution["evidence_references"])):
        raise LegalActorNotAuthorised("verified legal-actor identity/evidence mismatch")
    try:
        evaluated = datetime.fromisoformat(str(resolution["evaluated_at"]).replace("Z", "+00:00"))
        valid_until = datetime.fromisoformat(str(resolution["valid_until"]).replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError) as exc:
        raise LegalActorNotAuthorised("missing or invalid validity evidence") from exc
    if (evaluated.tzinfo is None or valid_until.tzinfo is None or now.tzinfo is None or
            evaluated > now + timedelta(seconds=1) or
            now - evaluated > _MAX_DECISION_AGE or
            valid_until <= now or valid_until > evaluated + _MAX_DECISION_AGE + timedelta(seconds=1)):
        raise LegalActorNotAuthorised("expired or stale legal-actor decision")
    return str(resolution["mandate_id"])


def perform_governed_financial_action(
    operation: LegalActorOperation,
    *,
    assessor: LegalActorAssessor,
    provider: LegalActorProviderReadiness,
    execute: Callable[[], _T],
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> _T:
    """Fail closed BEFORE any native iDempiere mutation, including a replay.

    CP LegalActorResolution does not certify ERP baseline, statutory posting
    permission, iDempiere AD_Client/AD_Org mapping, accounting period or tax
    configuration. A separate provider adapter MUST assert those facts.
    """
    operation.validate()
    if assessor is None or provider is None or execute is None:
        raise LegalActorNotAuthorised("CP assessment and ERP provider readiness required")
    decision = assessor.assess({
        "context_id": operation.context_id,
        "role": operation.role,
        "activity": operation.activity,
        "market": operation.market,
        "capability": operation.capability,
        "operation_reference": operation.operation_reference,
    })
    if not isinstance(decision, dict):
        raise LegalActorNotAuthorised("CP legal actor assessment unavailable")
    mandate = assert_current_decision(operation, decision, now=now())
    provider.ensure_legal_actor_usable(operation, mandate)
    return execute()
