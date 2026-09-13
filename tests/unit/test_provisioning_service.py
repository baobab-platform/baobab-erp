import unittest

from provisioning.model import ReadinessCheck
from provisioning.service import ErpProvisioningService
from test_provisioning_planner import valid_request


class MemoryStore:
    def __init__(self): self.operation = None; self.plan_value = None; self.steps = {}; self.status = None
    def create_or_get(self, provisioning_id, idempotency_key, desired_state_digest, desired_state): self.operation = provisioning_id; return provisioning_id
    def save_plan(self, plan): self.plan_value = plan
    def mark_step(self, provisioning_id, step_key, status, result): self.steps[step_key] = status
    def completed_steps(self, provisioning_id): return frozenset(key for key, status in self.steps.items() if status == "completed")
    def set_status(self, provisioning_id, status, error=None): self.status = status


class Adapter:
    def __init__(self): self.applied = []
    def apply(self, request, step): self.applied.append(step.key); return {"ok": True}
    def check(self, request, step): return ReadinessCheck(f"step.{step.key}", True, "reconciled")


class ProvisioningServiceTests(unittest.TestCase):
    def test_apply_is_retry_safe(self):
        store, adapter = MemoryStore(), Adapter()
        service = ErpProvisioningService(store, adapter)
        request = valid_request()
        plan = service.plan(request)
        service.apply(request, plan)
        first_count = len(adapter.applied)
        service.apply(request, plan)
        self.assertEqual(len(adapter.applied), first_count)
        self.assertTrue(service.readiness(request, plan).ready)


if __name__ == "__main__":
    unittest.main()
