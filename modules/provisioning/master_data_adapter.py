from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol
from provisioning.master_data import CanonicalMasterRecord, BootstrapResult, MasterDataKind
from provisioning.master_data_mapping import MasterDataMappingStore


class MasterDataIdempiereClient(Protocol):
    def get_record(self, table: str, record_id: int) -> dict[str, Any]: ...
    def create_record(self, table: str, fields: dict[str, Any]) -> int: ...
    def update_record(self, table: str, record_id: int, fields: dict[str, Any]) -> None: ...


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
    """Digest-and-version-reconciled master-data bootstrapper.

    Per ADR-ERP-014 INV-ERP-MD-027 ("consumers do not overwrite newer source
    versions with stale updates"), an incoming record whose source_version is
    not newer than what's already mapped never overwrites the native record
    even if its digest differs -- it is reported as drift for a human/steward
    to reconcile, since a numeric version regression usually means an
    out-of-order or replayed delivery rather than a real change.
    """
    client: MasterDataIdempiereClient
    mappings: MasterDataMappingStore

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
                native_id, old_digest, old_source_version=mapped
                self.client.get_record(table,native_id)
                if old_digest == digest:
                    reused += 1; continue
                if self._is_stale(r.source_version, old_source_version):
                    drift.append(
                        f"{r.canonical_id}: incoming source_version {r.source_version!r} is not newer than "
                        f"mapped {old_source_version!r}; not applying, needs reconciliation"
                    )
                    continue
                self.client.update_record(table,native_id,fields)
                self.mappings.put(engine_instance_id=engine_instance_id,legal_entity_id=legal_entity_id,
                                  kind=r.kind.value,canonical_id=r.canonical_id,native_id=native_id,
                                  desired_digest=digest,source_version=r.source_version)
                updated += 1
            else:
                native_id=self.client.create_record(table,fields)
                self.mappings.put(engine_instance_id=engine_instance_id,legal_entity_id=legal_entity_id,
                                  kind=r.kind.value,canonical_id=r.canonical_id,native_id=native_id,
                                  desired_digest=digest,source_version=r.source_version)
                created += 1
        return BootstrapResult(created+reused+updated+len(drift),created,reused,updated,tuple(drift))

    @staticmethod
    def _is_stale(incoming_version: str, mapped_version: str) -> bool:
        try:
            return int(incoming_version) < int(mapped_version)
        except ValueError:
            return False

    @staticmethod
    def _fields(r: CanonicalMasterRecord):
        p=dict(r.payload)
        p.setdefault("Value",r.external_key)
        p.setdefault("IsActive",True)
        return p
