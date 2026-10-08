"""The iDempiere process ids provisioning runs to configure accounting and localisation (ADR-ERP-019 §36, §42).

iDempiere assigns process ids per installation, so they are deployment configuration, never a default and never guessed. The
planner emits steps without them (the plan, and its digest, must not depend on which installation runs it); the executor adds the
id for a step just before running it. A step whose process is not configured is *blocked* before the operation touches the engine
at all: creating an AD_Client that cannot then be configured would leave a half-provisioned legal entity.

Configuration (all-or-nothing, like the order-to-cash process ids):
* ``IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING``: the process id that applies the approved accounting baseline;
* ``IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON``: ``{"<ISO country>": <process id>}``, one certified localisation per country.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping

from provisioning.model import ProvisioningStep, StepKind

ACCOUNTING_ENV = "IDEMPIERE_PROVISIONING_PROCESS_ACCOUNTING"
LOCALISATION_ENV = "IDEMPIERE_PROVISIONING_PROCESS_LOCALISATION_JSON"


class ProcessUnconfigured(Exception):
    """A step needs an iDempiere process id this deployment has not configured."""


@dataclass(frozen=True, slots=True)
class NativeProvisioningProcesses:
    accounting_process_id: int
    localisation_process_ids: Mapping[str, int]

    def enrich(self, step: ProvisioningStep) -> ProvisioningStep:
        """The step with its process id; steps that run no process pass through unchanged."""
        if step.kind is StepKind.CONFIGURE_ACCOUNTING:
            return ProvisioningStep(step.key, step.kind, {**step.payload, "process_id": self.accounting_process_id})
        if step.kind is StepKind.CONFIGURE_LOCALISATION:
            country = step.payload["country_code"]
            if country not in self.localisation_process_ids:
                raise ProcessUnconfigured(f"no certified localisation process is configured for {country}")
            return ProvisioningStep(step.key, step.kind, {**step.payload, "process_id": self.localisation_process_ids[country]})
        return step


def enrich_step(processes: NativeProvisioningProcesses | None, step: ProvisioningStep) -> ProvisioningStep:
    if step.kind not in (StepKind.CONFIGURE_ACCOUNTING, StepKind.CONFIGURE_LOCALISATION):
        return step
    if processes is None:
        raise ProcessUnconfigured("the native provisioning processes are not configured")
    return processes.enrich(step)


def load_native_processes(environ: Mapping[str, str] | None = None) -> NativeProvisioningProcesses | None:
    env = os.environ if environ is None else environ
    accounting, localisation = env.get(ACCOUNTING_ENV), env.get(LOCALISATION_ENV)
    if not accounting and not localisation:
        return None
    if not accounting or not localisation:
        raise RuntimeError(f"native provisioning processes are partly configured; set both {ACCOUNTING_ENV} and {LOCALISATION_ENV} or neither")
    try:
        by_country = {str(country): int(process) for country, process in json.loads(localisation).items()}
        return NativeProvisioningProcesses(int(accounting), by_country)
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"{ACCOUNTING_ENV} / {LOCALISATION_ENV} are not valid: {type(exc).__name__}") from None
