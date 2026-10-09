"""LA-05D3 guarded wrapper for the existing iDempiere invoice-posting path.

Caller MUST explicitly route an invoice posting through this function; old
order_to_cash.service.post_customer_invoice remains legacy compatibility and
does not itself provide legal actor enforcement until all call sites migrate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from order_to_cash.legal_actor_gate import (
    LegalActorAssessor, LegalActorNotAuthorised, LegalActorOperation,
    LegalActorProviderReadiness, perform_governed_financial_action,
)
from order_to_cash.model import TenantScope
from order_to_cash.service import (
    ConsequenceStore, IdempiereClient, MappingStore,
    OutboxStore, ProcessIds, post_customer_invoice,
)
from order_to_cash import accounting_outcomes as outcomes_rules


def post_customer_invoice_governed(
    *,
    operation: LegalActorOperation,
    assessor: LegalActorAssessor,
    provider: LegalActorProviderReadiness,
    scope: TenantScope,
    invoice_canonical_id: str,
    correlation_id: str,
    process_ids: ProcessIds,
    idempiere: IdempiereClient,
    mappings: MappingStore,
    outbox: OutboxStore,
    consequences: ConsequenceStore | None = None,
    outcomes: outcomes_rules.DocumentOutcomeStore | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> None:
    # The routing tenant/entity alone is never evidence of role authority.
    # This equality is a necessary, not sufficient, condition; the PEP also
    # asks CP and the independent native financial provider adapter.
    if (operation.role != "INVOICE_ISSUER"
        or operation.capability != "accounting.customer-invoice.post"
        or operation.operation_reference != invoice_canonical_id
        or operation.tenant_id != scope.tenant_id
        or operation.expected_legal_entity_id != scope.legal_entity_id):
        raise LegalActorNotAuthorised("invoice posting legal actor context mismatch")
    return perform_governed_financial_action(
        operation,
        assessor=assessor,
        provider=provider,
        now=now,
        execute=lambda: post_customer_invoice(
            scope=scope,
            invoice_canonical_id=invoice_canonical_id,
            correlation_id=correlation_id,
            process_ids=process_ids,
            idempiere=idempiere,
            mappings=mappings,
            outbox=outbox,
            consequences=consequences,
            outcomes=outcomes,
        ),
    )
