from dataclasses import dataclass
from provisioning.cp_contract import ControlPlaneAssignmentSource, FinanceBaseline, materialize_request
from provisioning.model import ErpProvisioningRequest


@dataclass(slots=True)
class AuthoritativeProvisioningRequestFactory:
    control_plane: ControlPlaneAssignmentSource

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
        return materialize_request(assignment, finance)
