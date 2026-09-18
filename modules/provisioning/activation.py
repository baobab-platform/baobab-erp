from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class ActivationEvidenceError(ValueError): pass


@dataclass(frozen=True, slots=True)
class Evidence:
    check: str
    status: GateStatus
    reference: str
    reason: str = ""

    def __post_init__(self):
        if not self.check.strip():
            raise ActivationEvidenceError("check name is required")
        if self.status is GateStatus.PASS and not self.reference.strip():
            raise ActivationEvidenceError(
                f"{self.check}: a passing gate requires a non-empty evidence reference -- "
                "READY is evidence, not an implicit production activation"
            )


@dataclass(frozen=True, slots=True)
class ActivationReport:
    legal_entity_id: str
    ready: bool
    evidence: tuple[Evidence, ...]
    blockers: tuple[str, ...]


class ActivationEvaluator:
    """Evaluates whether a single LegalEntity's activation evidence clears every
    mandatory production gate (ADR-ERP-020 SS9: 'ready' means all mandatory production
    gates have passed). Always evaluated per LegalEntity -- SS220 "independent
    activation": one organisation's readiness never forces another's, so
    Zuribeans_ZA and Zuribeans_UG may reach READY on entirely separate timelines.
    """

    REQUIRED = frozenset({
        "cp_assignment", "idempiere_provisioning", "localisation", "warehouses",
        "master_data", "procurement_golden", "sales_golden", "inventory_golden",
        "fx_golden", "reconciliation",
    })

    def evaluate(self, legal_entity_id: str, evidence: Iterable[Evidence]) -> ActivationReport:
        items = tuple(evidence)
        by: dict[str, Evidence] = {}
        for e in items:
            if e.check in by:
                raise ActivationEvidenceError(f"duplicate evidence submitted for {e.check!r}")
            by[e.check] = e
        blockers = []
        for name in sorted(self.REQUIRED):
            e = by.get(name)
            if e is None: blockers.append(f"{name}: missing evidence")
            elif e.status != GateStatus.PASS: blockers.append(f"{name}: {e.reason or 'failed'}")
        return ActivationReport(legal_entity_id, not blockers, items, tuple(blockers))
