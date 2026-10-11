"""ADR-BCP-027 LA-05D5 — exact, provider-certified native ERP action guard.

No default capability keys are invented here. A separately approved runtime
composition MUST inject the exact Shared/provider registry binding per action
and its evidence reference, or a command is denied before any native mutation.
This module never publishes a provider-support or production-ready claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypeVar

from order_to_cash.documentary_restriction import DocumentaryRestrictionAssessor
from order_to_cash.governed_service import _DocumentaryAndNativeReadiness
from order_to_cash.legal_actor_gate import (
    LegalActorAssessor, LegalActorNotAuthorised, LegalActorOperation,
    LegalActorProviderReadiness, perform_governed_financial_action,
)
from order_to_cash.model import TenantScope
from order_to_cash.service import _authorised_native_action

_T = TypeVar("_T")

# "post_customer_invoice" retains its separately tested LA-05D4 issuer gate.
_ACTION_ROLE = {
    "create_sales_order": "CONTRACTING_PARTY",
    "complete_sales_order": "CONTRACTING_PARTY",
    "create_shipment": "CONTRACTING_PARTY",
    "complete_shipment": "CONTRACTING_PARTY",
    "create_customer_invoice": "INVOICE_ISSUER",
    "create_payment": "ACCOUNTING_ENTITY",
    "complete_payment": "ACCOUNTING_ENTITY",
    "allocate_payment": "ACCOUNTING_ENTITY",
}


@dataclass(frozen=True, slots=True)
class NativeActionPolicy:
    """Trusted, reviewed per-action binding from canonical provider declarations."""
    action: str
    activity: str
    capability: str
    authority_reference: str


def perform_governed_native_action(
    *,
    policy: NativeActionPolicy | None,
    operation: LegalActorOperation,
    scope: TenantScope,
    resource_reference: str,
    assessor: LegalActorAssessor,
    provider: LegalActorProviderReadiness,
    documentary: DocumentaryRestrictionAssessor | None,
    execute: Callable[[], _T],
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> _T:
    """Authorise ONE native operation, never the tenant's default legal entity.

    Wrapper must be used by the protected, operation-specific composition root,
    not exposed directly as an applicant- or provider-selected policy surface.
    The exact resource identifier is part of the ephemeral native permit.
    """
    if (policy is None or policy.action not in _ACTION_ROLE or
            not policy.activity or not policy.capability or
            not policy.authority_reference or
            operation.role != _ACTION_ROLE[policy.action] or
            operation.activity != policy.activity or
            operation.capability != policy.capability or
            operation.tenant_id != scope.tenant_id or
            operation.expected_legal_entity_id != scope.legal_entity_id or
            operation.operation_reference != resource_reference or
            not resource_reference or assessor is None or provider is None or
            documentary is None or execute is None):
        raise LegalActorNotAuthorised(
            "exact approved ERP action, responsible actor, documentary and "
            "provider contract binding required"
        )

    def protected_native_call() -> _T:
        with _authorised_native_action(scope, policy.action, resource_reference):
            return execute()

    return perform_governed_financial_action(
        operation,
        assessor=assessor,
        provider=_DocumentaryAndNativeReadiness(provider, documentary, now),
        execute=protected_native_call,
        now=now,
    )
