from datetime import date, datetime, timedelta, timezone
import pytest
from provisioning.cp_contract import (
    AssignmentError, CpErpAssignment, CpMarketAssignment, NativeClientMode
)

def assignment(code: str, entity: str, market: str, country: str) -> CpErpAssignment:
    now = datetime.now(timezone.utc)
    return CpErpAssignment(
        assignment_version="v1", provisioning_id=f"prov-{code}",
        idempotency_key=f"idem-{code}", tenant_id="tenant-zuribeans",
        legal_entity_id=entity, legal_entity_code=code, legal_name=code,
        registration_identifier=f"REG-{code}", jurisdiction_code=country,
        engine_instance_id="erp-af-01", isolation_profile_id="iso-zb",
        capability_binding_id=f"binding-{code}", target_environment="production",
        effective_date=date(2026, 9, 1), native_client_mode=NativeClientMode.DEDICATED_CLIENT,
        native_client_key=code,
        markets=(CpMarketAssignment(market, country, frozenset({"selling","procurement"}), ("ZAR",) if country=="ZA" else ("UGX",), f"{country.lower()}-v1"),),
        requested_capabilities=frozenset({"erp.accounting","erp.accounts-payable","erp.accounts-receivable","erp.inventory","erp.procurement"}),
        issued_at=now, expires_at=now + timedelta(hours=1),
    )

def test_za_and_ug_are_distinct_legal_entities_and_native_boundaries():
    za = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
    ug = assignment("Zuribeans_UG", "le-zb-ug", "market-ug", "UG")
    za.validate(); ug.validate()
    assert za.legal_entity_id != ug.legal_entity_id
    assert za.native_client_key != ug.native_client_key

def test_expired_assignment_fails_closed():
    a = assignment("Zuribeans_ZA", "le-zb-za", "market-za", "ZA")
    object.__setattr__(a, "expires_at", datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(AssignmentError):
        a.validate()
