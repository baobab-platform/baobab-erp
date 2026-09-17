from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from provisioning.master_data import CanonicalMasterRecord, BootstrapResult, MasterDataKind


TABLES={
 MasterDataKind.PRODUCT:"M_Product",
 MasterDataKind.UOM:"C_UOM",
 MasterDataKind.BUSINESS_PARTNER:"C_BPartner",
 MasterDataKind.CURRENCY:"C_Currency",
 MasterDataKind.TAX_CATEGORY:"C_TaxCategory",
 MasterDataKind.PAYMENT_TERM:"C_PaymentTerm",
}

@dataclass(slots=True)
class IdempiereMasterDataBootstrapper:
    client: Any
    mappings: Any

    def bootstrap(self, *, engine_instance_id: str, legal_entity_id: str, records) -> BootstrapResult:
        created=reused=updated=0; drift=[]
        for r in records:
            r.validate()
            if r.legal_entity_id != legal_entity_id:
                raise ValueError(f"cross-legal-entity master data: {r.canonical_id}")
            if r.kind == MasterDataKind.PRODUCT_ACCOUNTING:
                drift.append(f"{r.canonical_id}: product accounting requires approved accounting process")
                continue
            table=TABLES[r.kind]
            digest=r.digest()
            mapped=self.mappings.get(engine_instance_id=engine_instance_id,legal_entity_id=legal_entity_id,
                                     kind=r.kind.value,canonical_id=r.canonical_id)
            fields=self._fields(r)
            if mapped:
                native_id, old_digest=mapped
                self.client.get_record(table,native_id)
                if old_digest == digest:
                    reused += 1; continue
                self.client.update_record(table,native_id,fields)
                self.mappings.put(engine_instance_id=engine_instance_id,legal_entity_id=legal_entity_id,
                                  kind=r.kind.value,canonical_id=r.canonical_id,native_id=native_id,desired_digest=digest)
                updated += 1
            else:
                native_id=self.client.create_record(table,fields)
                self.mappings.put(engine_instance_id=engine_instance_id,legal_entity_id=legal_entity_id,
                                  kind=r.kind.value,canonical_id=r.canonical_id,native_id=native_id,desired_digest=digest)
                created += 1
        return BootstrapResult(created+reused+updated+len(drift),created,reused,updated,tuple(drift))

    @staticmethod
    def _fields(r: CanonicalMasterRecord):
        p=dict(r.payload)
        p.setdefault("Value",r.external_key)
        p.setdefault("IsActive",True)
        return p
