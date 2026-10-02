from dataclasses import dataclass
from provisioning.cp_contract import ControlPlaneAssignmentSource, FinanceBaseline, materialize_request
from provisioning.legal_entity_policy import NativeClientMode, NativePlacementPolicy, native_boundary
from provisioning.model import ErpProvisioningRequest


@dataclass(slots=True)
class AuthoritativeProvisioningRequestFactory:
    control_plane: ControlPlaneAssignmentSource
    native_placement: NativePlacementPolicy

    def build(
        self,
        *,
        tenant_id: str,
        legal_entity_id: str,
        finance: FinanceBaseline,
        capability_key: str = "erp.accounting",
    ) -> ErpProvisioningRequest:
        assignment = self.control_plane.resolve_erp_assignment(
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            capability_key=capability_key,
        )
        if assignment.tenant_id != tenant_id or assignment.legal_entity_id != legal_entity_id:
            raise ValueError("Control Plane returned a cross-boundary ERP assignment")
        # Native placement is ERP-owned (ADR-ERP-002 SS114). The provisioning adapter
        # (modules/provisioning/idempiere_adapter.py, Gate ZB-02) only ever creates a new AD_Client -- it
        # has no "reuse an existing AD_Client" path -- so any other configured mode fails closed here
        # rather than silently misprovisioning.
        boundary = native_boundary(assignment, self.native_placement)
        if boundary.mode is not NativeClientMode.DEDICATED_CLIENT:
            raise NotImplementedError(
                f"native_client_mode={boundary.mode.value!r} is not supported by the "
                "provisioning adapter (only dedicated_client creates a real AD_Client today)"
            )
        return materialize_request(assignment, finance)
