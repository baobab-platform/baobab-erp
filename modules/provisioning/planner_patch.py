"""Replacement build_plan showing the production adapter-required payload.

Integrate this into provisioning/planner.py after assigning approved iDempiere
process IDs from deployment configuration. Do not hard-code unverified process IDs.
"""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class NativeProvisioningProcesses:
    accounting_process_id: int
    localisation_process_ids: dict[str, int]

def enrich_step_payload(kind: str, payload: dict, processes: NativeProvisioningProcesses) -> dict:
    result = dict(payload)
    if kind == "configure_accounting":
        result["process_id"] = processes.accounting_process_id
    elif kind == "configure_localisation":
        country = result["country_code"]
        if country not in processes.localisation_process_ids:
            raise ValueError(f"no certified localisation process configured for {country}")
        result["process_id"] = processes.localisation_process_ids[country]
    return result
