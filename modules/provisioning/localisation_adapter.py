from __future__ import annotations
from dataclasses import dataclass
from provisioning.localisation import LocalisationRegistry


@dataclass(slots=True)
class LocalisationProvisioner:
    client: object
    registry: LocalisationRegistry

    def apply(self, *, profile_key: str, country_code: str, effective_date, parameters: dict) -> dict:
        profile=self.registry.require(profile_key, country_code=country_code, on=effective_date)
        payload=dict(parameters)
        payload.update({
            "country_code": country_code,
            "localisation_profile": profile.profile_key,
            "localisation_version": profile.version,
            "certification_reference": profile.certification_reference,
        })
        return self.client.execute_process(profile.process_id, payload)
