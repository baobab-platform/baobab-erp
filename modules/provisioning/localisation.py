from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Mapping


class LocalisationError(ValueError): pass


@dataclass(frozen=True, slots=True)
class CertifiedLocalisation:
    profile_id: str
    country_code: str
    version: str
    effective_from: date
    effective_to: date | None
    process_id: int
    certification_reference: str

    def effective_on(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day < self.effective_to)


class LocalisationRegistry:
    def __init__(self, profiles: Mapping[str, CertifiedLocalisation]) -> None:
        self._profiles=dict(profiles)

    def require(self, key: str, *, country_code: str, on: date) -> CertifiedLocalisation:
        p=self._profiles.get(key)
        if p is None: raise LocalisationError(f"unknown localisation profile {key!r}")
        if p.country_code != country_code:
            raise LocalisationError(f"profile {key!r} belongs to {p.country_code}, not {country_code}")
        if not p.certification_reference.strip():
            raise LocalisationError(f"profile {key!r} is not certified")
        if not p.effective_on(on):
            raise LocalisationError(f"profile {key!r} is not effective on {on.isoformat()}")
        if p.process_id <= 0:
            raise LocalisationError(f"profile {key!r} has no approved iDempiere process")
        return p
