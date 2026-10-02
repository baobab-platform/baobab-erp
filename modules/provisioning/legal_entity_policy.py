"""ERP-owned native placement (ADR-ERP-002 SS114, ADR-ERP-021).

Control Plane assigns the LegalEntity, EngineInstance, IsolationProfile and CapabilityBinding. Which native
AD_Client a LegalEntity lands in is an ERP provider decision constrained by that isolation, so it is configured
here explicitly and fails closed. Nothing is inferred from a country code, a name or a currency.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

from provisioning.cp_contract import AssignmentError, CpErpAssignment


class NativeClientMode(StrEnum):
    DEDICATED_CLIENT = "dedicated_client"
    EXISTING_CLIENT = "existing_client"


@dataclass(frozen=True, slots=True)
class NativePlacement:
    native_client_key: str
    mode: NativeClientMode = NativeClientMode.DEDICATED_CLIENT


@dataclass(frozen=True, slots=True)
class NativeBoundary:
    legal_entity_id: str
    legal_entity_code: str
    native_client_key: str
    mode: NativeClientMode


class NativePlacementPolicy(Protocol):
    def placement_for(self, assignment: CpErpAssignment) -> NativePlacement: ...


class ConfiguredNativePlacementPolicy:
    """Explicit placements keyed by the canonical LegalEntity code (ADR-ERP-021 names Zuribeans_ZA / Zuribeans_UG)."""

    def __init__(self, placements: Mapping[str, NativePlacement]):
        self._placements = dict(placements)

    def placement_for(self, assignment: CpErpAssignment) -> NativePlacement:
        try:
            return self._placements[assignment.legal_entity_code]
        except KeyError:
            raise AssignmentError(
                f"no ERP native placement is configured for legal entity {assignment.legal_entity_code!r}"
            ) from None


def native_boundary(assignment: CpErpAssignment, policy: NativePlacementPolicy) -> NativeBoundary:
    assignment.validate()
    placement = policy.placement_for(assignment)
    if not placement.native_client_key.strip():
        raise AssignmentError("native placement has an empty native_client_key")
    return NativeBoundary(
        legal_entity_id=assignment.legal_entity_id,
        legal_entity_code=assignment.legal_entity_code,
        native_client_key=placement.native_client_key,
        mode=placement.mode,
    )
