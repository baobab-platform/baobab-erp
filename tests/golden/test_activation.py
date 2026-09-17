from provisioning.activation import *
def test_missing_golden_path_blocks_activation():
 e=[Evidence(x,GateStatus.PASS,"ref") for x in ActivationEvaluator.REQUIRED if x!="fx_golden"]
 r=ActivationEvaluator().evaluate("le-za",e)
 assert not r.ready and any("fx_golden" in b for b in r.blockers)
def test_all_evidence_allows_ready():
 e=[Evidence(x,GateStatus.PASS,"ref") for x in ActivationEvaluator.REQUIRED]
 assert ActivationEvaluator().evaluate("le-ug",e).ready
