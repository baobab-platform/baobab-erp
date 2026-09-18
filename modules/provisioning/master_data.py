from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Iterable, Protocol


class MasterDataError(ValueError): pass


class MasterDataKind(StrEnum):
    PRODUCT = "product"
    UOM = "uom"
    BUSINESS_PARTNER = "business_partner"
    CURRENCY = "currency"
    TAX_CATEGORY = "tax_category"
    PAYMENT_TERM = "payment_term"
    PRODUCT_ACCOUNTING = "product_accounting"


@dataclass(frozen=True, slots=True)
class CanonicalMasterRecord:
    kind: MasterDataKind
    canonical_id: str
    external_key: str
    legal_entity_id: str
    payload: dict[str, Any]
    contract_version: str
    source_version: str

    def validate(self) -> None:
        if not self.canonical_id.strip(): raise MasterDataError("canonical_id is required")
        if not self.external_key.strip(): raise MasterDataError("external_key is required")
        if not self.legal_entity_id.strip(): raise MasterDataError("legal_entity_id is required")
        if not self.contract_version.strip(): raise MasterDataError("contract_version is required")
        if not self.source_version.strip(): raise MasterDataError("source_version is required")

    def digest(self) -> str:
        self.validate()
        raw=json.dumps({
            "kind": self.kind.value, "canonical_id": self.canonical_id,
            "external_key": self.external_key, "legal_entity_id": self.legal_entity_id,
            "payload": self.payload, "contract_version": self.contract_version,
            "source_version": self.source_version,
        }, sort_keys=True, separators=(",",":"), ensure_ascii=False)
        return sha256(raw.encode()).hexdigest()


class CanonicalMasterDataSource(Protocol):
    def list_records(self, *, tenant_id: str, legal_entity_id: str) -> Iterable[CanonicalMasterRecord]: ...


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    desired: int
    created: int
    reused: int
    updated: int
    drift: tuple[str, ...] = ()
