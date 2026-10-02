from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from provisioning.cp_contract import (
    AssignmentError,
    ControlPlaneAssignmentSource,
    ErpMarketConfiguration,
    FinanceBaseline,
    materialize_request,
)
from provisioning.finance_baseline_store import FinanceBaselineSource
from provisioning.legal_entity_policy import NativeClientMode, NativePlacementPolicy, native_boundary
from provisioning.model import ErpProvisioningRequest


@dataclass(slots=True)
class AuthoritativeProvisioningRequestFactory:
    control_plane: ControlPlaneAssignmentSource
    native_placement: NativePlacementPolicy
    market_configuration: Mapping[str, ErpMarketConfiguration]
    finance: FinanceBaselineSource
    target_environment: str

    def build(
        self,
        *,
        tenant_id: str,
        tenant_provisioning_id: str,
        legal_entity_id: str,
        on: date,
        now: datetime | None = None,
    ) -> ErpProvisioningRequest:
        assignment = self.control_plane.resolve_erp_assignment(
            tenant_id=tenant_id, tenant_provisioning_id=tenant_provisioning_id, legal_entity_id=legal_entity_id)
        # Request is not authority: the assignment must be for exactly what was asked, not merely well-formed.
        if (assignment.tenant_id, assignment.tenant_provisioning_id, assignment.legal_entity_id) != (
                tenant_id, tenant_provisioning_id, legal_entity_id):
            raise AssignmentError("Control Plane returned a cross-boundary ERP assignment")
        # Native placement is ERP-owned (ADR-ERP-002 SS114). The provisioning adapter
        # (modules/provisioning/idempiere_adapter.py, Gate ZB-02) only ever creates a new AD_Client -- it
        # has no "reuse an existing AD_Client" path -- so any other configured mode fails closed here
        # rather than silently misprovisioning.
        boundary = native_boundary(assignment, self.native_placement, now)
        if boundary.mode is not NativeClientMode.DEDICATED_CLIENT:
            raise NotImplementedError(
                f"native_client_mode={boundary.mode.value!r} is not supported by the "
                "provisioning adapter (only dedicated_client creates a real AD_Client today)"
            )
        # The accounting configuration is Finance's (ADR-ERP-008): the baseline in force for exactly this legal entity,
        # with a named approver and evidence. None is not defaulted; it is "not provisionable yet".
        baseline = self.finance.effective(legal_entity_id, on)
        if baseline is None:
            raise AssignmentError(f"no Finance-approved baseline is in force for {legal_entity_id!r} on {on.isoformat()}")
        if baseline.legal_entity_id != legal_entity_id:
            raise AssignmentError("the Finance baseline belongs to another legal entity")
        return materialize_request(
            assignment,
            FinanceBaseline(
                functional_currency=baseline.functional_currency, fiscal_year_start_month=baseline.fiscal_year_start_month,
                chart_of_accounts_template=baseline.chart_of_accounts_template, accounting_schema=baseline.accounting_schema,
                tax_profile=baseline.tax_profile, costing_method=baseline.costing_method,
                approved_by=baseline.approved_by, approved_at=baseline.approved_at),
            self.market_configuration,
            target_environment=self.target_environment, effective_date=baseline.effective_from, now=now)
