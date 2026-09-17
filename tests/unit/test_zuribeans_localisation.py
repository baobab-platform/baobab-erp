from datetime import date
import pytest
from provisioning.localisation import CertifiedLocalisation, LocalisationRegistry, LocalisationError

def test_country_mismatch_fails_closed():
    r=LocalisationRegistry({"za": CertifiedLocalisation("za","ZA","1",date(2026,1,1),None,100,"CERT")})
    with pytest.raises(LocalisationError):
        r.require("za", country_code="UG", on=date(2026,9,1))

def test_certified_effective_profile_resolves():
    p=CertifiedLocalisation("ug","UG","1",date(2026,1,1),None,101,"CERT")
    assert LocalisationRegistry({"ug":p}).require("ug",country_code="UG",on=date(2026,9,1)) == p
