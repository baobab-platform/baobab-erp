from dataclasses import dataclass
from provisioning.cp_contract import CpErpAssignment, NativeClientMode


@dataclass(frozen=True, slots=True)
class NativeBoundary:
    legal_entity_id: str
    legal_entity_code: str
    native_client_key: str
    mode: NativeClientMode


def native_boundary(assignment: CpErpAssignment) -> NativeBoundary:
    """No LegalEntity→AD_Client/AD_Org inference is performed here.

    ADR-ERP-002 requires an explicit mapping. For ZuriBeans Release 1,
    Zuribeans_ZA and Zuribeans_UG are distinct canonical LegalEntities.
    CP must therefore provide a separately governed native_client_key/mode for
    each legal entity; ERP consumes rather than invents that decision.
    """
    assignment.validate()
    return NativeBoundary(
        legal_entity_id=assignment.legal_entity_id,
        legal_entity_code=assignment.legal_entity_code,
        native_client_key=assignment.native_client_key,
        mode=assignment.native_client_mode,
    )
