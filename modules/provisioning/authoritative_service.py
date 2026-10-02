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
from provisioning.legal_entity_policy import NativeClientMode, NativePlacementPolicy, native_boundary
from provisioning.model import ErpProvisioningRequest


@dataclass(slots=True)
class AuthoritativeProvisioningRequestFactory:
    control_plane: ControlPlaneAssignmentSource
    native_placement: NativePlacementPolicy
    market_configuration: Mapping[str, ErpMarketConfiguration]
    target_environment: str

    def build(
        self,
        *,
        tenant_id: str,
        tenant_provisioning_id: str,
        legal_entity_id: str,
        finance: FinanceBaseline,
        effective_date: date,
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
        return materialize_request(
            assignment, finance, self.market_configuration,
            target_environment=self.target_environment, effective_date=effective_date, now=now)
