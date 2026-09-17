from provisioning.master_data import CanonicalMasterRecord, MasterDataKind
from provisioning.master_data_adapter import IdempiereMasterDataBootstrapper

class C:
 def __init__(self): self.r={}; self.n=10
 def create_record(self,t,f): self.n+=1; self.r[(t,self.n)]=dict(f); return self.n
 def get_record(self,t,i): return self.r[(t,i)]
 def update_record(self,t,i,f): self.r[(t,i)].update(f)
class M:
 def __init__(self): self.m={}
 def get(self,**k): return self.m.get(tuple(k.values()))
 def put(self,**k):
  self.m[(k["engine_instance_id"],k["legal_entity_id"],k["kind"],k["canonical_id"])]=(k["native_id"],k["desired_digest"])

def test_idempotent_product_bootstrap():
 c=C(); m=M(); b=IdempiereMasterDataBootstrapper(c,m)
 r=CanonicalMasterRecord(MasterDataKind.PRODUCT,"prod-1","COFFEE-1","le-za",{"Name":"Coffee"},"v1","1")
 a=b.bootstrap(engine_instance_id="erp",legal_entity_id="le-za",records=[r])
 z=b.bootstrap(engine_instance_id="erp",legal_entity_id="le-za",records=[r])
 assert a.created==1 and z.reused==1 and len(c.r)==1

def test_cross_legal_entity_fails_closed():
 import pytest
 c=C();m=M();b=IdempiereMasterDataBootstrapper(c,m)
 r=CanonicalMasterRecord(MasterDataKind.PRODUCT,"p","P","le-ug",{"Name":"X"},"v1","1")
 with pytest.raises(ValueError): b.bootstrap(engine_instance_id="erp",legal_entity_id="le-za",records=[r])
