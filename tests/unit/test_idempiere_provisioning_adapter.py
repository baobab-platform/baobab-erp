from dataclasses import dataclass
from provisioning.idempiere_adapter import IdempiereProvisioningAdapter
from provisioning.model import ProvisioningStep, StepKind

class FakeClient:
    def __init__(self): self.records = {}; self.next = 100
    def create_record(self, table, fields):
        self.next += 1; self.records[(table,self.next)] = dict(fields); return self.next
    def get_record(self, table, record_id): return self.records[(table,record_id)]
    def update_record(self, table, record_id, fields): self.records[(table,record_id)].update(fields)
    def execute_process(self, process_id, parameters): return {"process_id": process_id, "ok": True}

class FakeMappings:
    def __init__(self): self.values = {}
    def get_native_id(self, *, provisioning_id, resource_key): return self.values.get((provisioning_id,resource_key))
    def put_native_id(self, *, provisioning_id, resource_key, native_id): self.values[(provisioning_id,resource_key)] = native_id

@dataclass
class Request:
    provisioning_id: str = "p1"
    legal_name: str = "Zuribeans South Africa"
    legal_entity_id: str = "le-zb-za"

def test_create_client_is_idempotent():
    c=FakeClient(); m=FakeMappings(); a=IdempiereProvisioningAdapter(c,m); r=Request()
    s=ProvisioningStep("client", StepKind.CREATE_CLIENT, {})
    first=a.apply(r,s); second=a.apply(r,s)
    assert first["id"] == second["id"]
    assert second["reused"] is True
    assert len(c.records) == 1

def test_accounting_fails_closed_without_approved_process():
    import pytest
    c=FakeClient(); m=FakeMappings(); a=IdempiereProvisioningAdapter(c,m); r=Request()
    s=ProvisioningStep("accounting", StepKind.CONFIGURE_ACCOUNTING, {})
    with pytest.raises(ValueError):
        a.apply(r,s)
