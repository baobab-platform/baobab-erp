"""Executes an accepted provisioning operation against its engine (ADR-ERP-019).

Acceptance (``command_store.accept``) records *what* to provision and returns 202; nothing then did it. This is the missing half,
run by ``application.provisioning_worker``. It reads the operation back, proves it is still what was approved, and drives the plan
through ``IdempiereProvisioningAdapter`` step by step, recording each step so a restart resumes where it stopped.

Guarantees, in the order a reviewer would ask for them:

* **Only what was approved runs.** The stored desired state is decoded and its plan digest recomputed; the stored plan must equal
  the plan rebuilt from it. Any difference is ``STATE_DRIFT`` and nothing touches the engine.
* **Nothing starts that cannot finish.** The engine session and every process id the plan needs are resolved *before* the first
  step, so a missing credential or process id blocks the operation instead of leaving an AD_Client with no accounting.
* **A repeat does not repeat work.** Completed steps are skipped, native ids are looked up before anything is created, and an
  engine record an earlier attempt created but never recorded is adopted by its marker (see the adapter). The caller holds a
  per-operation lock while this runs, so two workers cannot interleave.
* **Failure is classified, not guessed.** An engine that is down is retried with backoff, a missing credential or process id is
  *blocked* (an operator can fix it) and retried slowly, and a rejected or inconsistent request is failed. Failing records the
  fixed code; ``provisioning.command_state`` then reports the command failed without exposing internals.

This runs against a fake engine in CI. ``AD_Client`` creation through the REST plugin, ``Description`` as the marker column and the
process ids are what a live iDempiere run must still confirm (ERP-CAP-03).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Protocol

from integration.idempiere_client import IdempiereApiError, IdempiereAuthenticationError, IdempiereClientError
from order_to_cash.execution_policy import retry_delay_seconds
from provisioning.idempiere_adapter import DuplicateNativeRecords, IdempiereProvisioningAdapter
from provisioning.model import ProvisioningStatus, ProvisioningStep, StepKind
from provisioning.native_processes import NativeProvisioningProcesses, ProcessUnconfigured, enrich_step
from provisioning.planner import build_plan
from provisioning.request_state import StateDrift, StateUnreadable, verified_request
from provisioning.validation import InvalidProvisioningRequestError, validate_request

MAX_ATTEMPTS = 24
BLOCKED_DELAY_SECONDS = 900
BLOCKED_HORIZON = timedelta(hours=72)


class EngineUnconfigured(Exception):
    """No provisioner session is configured for the EngineInstance the legal entity is provisioned onto."""


class MappingConflict(Exception):
    """The tenant already maps to a different AD_Client/AD_Org/EngineInstance than this operation produced."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """How a pass ended. ``status``: ready, retry (engine trouble or readiness not yet met), blocked (operator action) or failed."""

    status: str
    code: str
    detail: str = ""
    delay_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class LoadedOperation:
    provisioning_id: str
    state: Mapping[str, Any]
    digest: str | None
    plan: tuple[Mapping[str, Any], ...]
    status: str
    attempts: int
    created_at: datetime


class StepStore(Protocol):
    def mark_step(self, provisioning_id: str, step_key: str, status: str, result: dict[str, Any]) -> None: ...
    def completed_steps(self, provisioning_id: str) -> frozenset[str]: ...
    def set_status(self, provisioning_id: str, status: ProvisioningStatus, error: str | None = None) -> None: ...


def classify(exc: Exception) -> Outcome:
    """The outcome of an exception. Details are fixed or type names: an engine message can carry tenant data, so it is never stored."""
    if isinstance(exc, StateUnreadable):
        return Outcome("failed", "STATE_UNREADABLE")
    if isinstance(exc, StateDrift):
        return Outcome("failed", "STATE_DRIFT")
    if isinstance(exc, EngineUnconfigured):
        return Outcome("blocked", "ENGINE_UNCONFIGURED")
    if isinstance(exc, ProcessUnconfigured):
        return Outcome("blocked", "PROCESS_UNCONFIGURED")
    if isinstance(exc, IdempiereAuthenticationError):
        return Outcome("blocked", "ENGINE_AUTH")
    if isinstance(exc, IdempiereApiError):
        if exc.status >= 500 or exc.status in (408, 425, 429):
            return Outcome("retry", "ENGINE_UNAVAILABLE", f"HTTP {exc.status}")
        return Outcome("failed", "ENGINE_REJECTED", f"HTTP {exc.status}")
    if isinstance(exc, IdempiereClientError):
        return Outcome("retry", "ENGINE_UNAVAILABLE")
    if isinstance(exc, DuplicateNativeRecords):
        return Outcome("failed", "DUPLICATE_NATIVE_RECORDS")
    if isinstance(exc, MappingConflict):
        return Outcome("failed", "TENANT_MAPPING_CONFLICT")
    if isinstance(exc, (InvalidProvisioningRequestError, ValueError)):
        return Outcome("failed", "STEP_INVALID", type(exc).__name__)
    return Outcome("retry", "UNEXPECTED_ERROR", type(exc).__name__)


def apply_budgets(outcome: Outcome, *, attempts: int, created_at: datetime, now: datetime) -> Outcome:
    """A retry past MAX_ATTEMPTS and a block past its horizon become failures; otherwise the delay is filled in."""
    if outcome.status == "retry":
        if attempts >= MAX_ATTEMPTS:
            return Outcome("failed", "ATTEMPTS_EXHAUSTED", outcome.code)
        return Outcome("retry", outcome.code, outcome.detail, retry_delay_seconds(attempts))
    if outcome.status == "blocked":
        if now - created_at > BLOCKED_HORIZON:
            return Outcome("failed", "BLOCKED_HORIZON_EXCEEDED", outcome.code)
        return Outcome("blocked", outcome.code, outcome.detail, BLOCKED_DELAY_SECONDS)
    return outcome


class ProvisioningExecutor:
    def __init__(self, *, store: StepStore, mappings, tenant_mappings, engine_for: Callable[[str], Any],
                 processes: NativeProvisioningProcesses | None) -> None:
        self._store = store
        self._mappings = mappings
        self._tenant_mappings = tenant_mappings
        self._engine_for = engine_for
        self._processes = processes

    def run(self, operation: LoadedOperation) -> Outcome:
        """One pass over the operation. Never raises: whatever goes wrong becomes a classified outcome."""
        try:
            return self._run(operation)
        except Exception as exc:  # noqa: BLE001 - classification is the point; unknown errors retry within the attempt budget
            return classify(exc)

    def _run(self, operation: LoadedOperation) -> Outcome:
        request = verified_request(operation.state, operation.digest)
        steps = tuple(ProvisioningStep(row["key"], StepKind(row["kind"]), dict(row["payload"])) for row in operation.plan)
        if steps != build_plan(request).steps:
            raise StateDrift("the stored plan is not the plan its desired state produces")
        client = self._engine_for(request.engine_instance_id)
        if client is None:
            raise EngineUnconfigured(request.engine_instance_id)
        runnable = tuple(enrich_step(self._processes, step) for step in steps)  # every process id, before the first step
        adapter = IdempiereProvisioningAdapter(client, self._mappings, self._tenant_mappings)
        done = self._store.completed_steps(operation.provisioning_id)
        pending = [step for step in runnable if step.key not in done]
        if pending and operation.status != ProvisioningStatus.APPLYING.value:
            self._store.set_status(operation.provisioning_id, ProvisioningStatus.APPLYING)
        for step in pending:
            result = adapter.apply(request, step)
            self._store.mark_step(operation.provisioning_id, step.key, "completed", result)
        if operation.status != ProvisioningStatus.RECONCILING.value:
            self._store.set_status(operation.provisioning_id, ProvisioningStatus.RECONCILING)
        checks = list(validate_request(request)) + [adapter.check(request, step) for step in runnable]
        failing = [check.code for check in checks if not check.ready]
        if failing:
            return Outcome("retry", "NOT_READY", ",".join(sorted(failing))[:200])
        self._store.set_status(operation.provisioning_id, ProvisioningStatus.READY)
        return Outcome("ready", "READY")
