from dataclasses import dataclass
from provisioning.master_data_adapter import IdempiereMasterDataBootstrapper

@dataclass(slots=True)
class MasterDataBootstrapService:
    source: object
    bootstrapper: IdempiereMasterDataBootstrapper

    def run(self, *, tenant_id: str, legal_entity_id: str, engine_instance_id: str):
        records=tuple(self.source.list_records(tenant_id=tenant_id,legal_entity_id=legal_entity_id))
        return self.bootstrapper.bootstrap(engine_instance_id=engine_instance_id,
                                           legal_entity_id=legal_entity_id,records=records)
