from dataclasses import dataclass
from enum import StrEnum

class GateStatus(StrEnum): PASS="pass"; FAIL="fail"

@dataclass(frozen=True,slots=True)
class Evidence:
    check:str
    status:GateStatus
    reference:str
    reason:str=""

@dataclass(frozen=True,slots=True)
class ActivationReport:
    legal_entity_id:str
    ready:bool
    evidence:tuple[Evidence,...]
    blockers:tuple[str,...]

class ActivationEvaluator:
    REQUIRED=frozenset({"cp_assignment","idempiere_provisioning","localisation","warehouses",
      "master_data","procurement_golden","sales_golden","inventory_golden","fx_golden","reconciliation"})
    def evaluate(self,legal_entity_id:str,evidence)->ActivationReport:
        items=tuple(evidence); by={e.check:e for e in items}
        blockers=[]
        for name in sorted(self.REQUIRED):
            e=by.get(name)
            if e is None: blockers.append(f"{name}: missing evidence")
            elif e.status != GateStatus.PASS: blockers.append(f"{name}: {e.reason or 'failed'}")
        return ActivationReport(legal_entity_id,not blockers,items,tuple(blockers))
