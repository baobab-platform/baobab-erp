from dataclasses import asdict
from typing import Protocol

from provisioning.model import ErpProvisioningRequest, ProvisioningPlan, ProvisioningReadiness, ProvisioningStatus, ProvisioningStep, ReadinessCheck
from provisioning.planner import build_plan
from provisioning.store import ProvisioningStore
from provisioning.validation import validate_request


class ProvisioningAdapter(Protocol):
    def apply(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> dict: ...
    def check(self, request: ErpProvisioningRequest, step: ProvisioningStep) -> ReadinessCheck: ...


class ErpProvisioningService:
    def __init__(self, store: ProvisioningStore, adapter: ProvisioningAdapter) -> None:
        self._store = store
        self._adapter = adapter

    def plan(self, request: ErpProvisioningRequest) -> ProvisioningPlan:
        plan = build_plan(request)
        existing_id = self._store.create_or_get(
            request.provisioning_id,
            request.idempotency_key,
            plan.desired_state_digest,
            asdict(request),
        )
        if existing_id != request.provisioning_id:
            raise ValueError(f"idempotency key already belongs to provisioning operation {existing_id}")
        self._store.save_plan(plan)
        return plan

    def apply(self, request: ErpProvisioningRequest, plan: ProvisioningPlan) -> None:
        completed = self._store.completed_steps(plan.provisioning_id)
        self._store.set_status(plan.provisioning_id, ProvisioningStatus.APPLYING)
        try:
            for step in plan.steps:
                if step.key in completed:
                    continue
                result = self._adapter.apply(request, step)
                self._store.mark_step(plan.provisioning_id, step.key, "completed", result)
        except Exception as exc:
            self._store.set_status(plan.provisioning_id, ProvisioningStatus.FAILED, str(exc))
            raise
        self._store.set_status(plan.provisioning_id, ProvisioningStatus.RECONCILING)

    def readiness(self, request: ErpProvisioningRequest, plan: ProvisioningPlan) -> ProvisioningReadiness:
        checks = list(validate_request(request))
        checks.extend(self._adapter.check(request, step) for step in plan.steps)
        result = ProvisioningReadiness(plan.provisioning_id, tuple(checks))
        self._store.set_status(plan.provisioning_id, ProvisioningStatus.READY if result.ready else ProvisioningStatus.RECONCILING)
        return result
