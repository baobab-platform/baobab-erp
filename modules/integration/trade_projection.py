from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Protocol

class ProjectionError(ValueError): pass
class TransactionKind(StrEnum):
    PROCUREMENT_ORDER="procurement_order"
    SALES_ORDER="sales_order"
    GOODS_RECEIPT="goods_receipt"
    SHIPMENT="shipment"
    AP_INVOICE="ap_invoice"
    AR_INVOICE="ar_invoice"
    PAYMENT="payment"

@dataclass(frozen=True,slots=True)
class Line:
    canonical_product_id:str
    quantity:Decimal
    unit_price:Decimal
    uom_id:str

@dataclass(frozen=True,slots=True)
class TradeProjection:
    event_id:str
    correlation_id:str
    tenant_id:str
    legal_entity_id:str
    market_id:str
    engine_instance_id:str
    kind:TransactionKind
    canonical_transaction_id:str
    counterparty_id:str
    currency:str
    lines:tuple[Line,...]
    contract_version:str
    payload:dict[str,Any]

    def validate(self):
        for n in ("event_id","correlation_id","tenant_id","legal_entity_id","market_id",
                  "engine_instance_id","canonical_transaction_id","counterparty_id","currency","contract_version"):
            if not str(getattr(self,n)).strip(): raise ProjectionError(f"{n} is required")
        if self.kind not in {TransactionKind.PAYMENT} and not self.lines:
            raise ProjectionError("transaction lines required")
        for l in self.lines:
            if l.quantity <= 0: raise ProjectionError("quantity must be positive")
            if l.unit_price < 0: raise ProjectionError("unit price cannot be negative")

    def digest(self):
        self.validate()
        raw=json.dumps({"kind":self.kind.value,"id":self.canonical_transaction_id,
            "legal_entity_id":self.legal_entity_id,"market_id":self.market_id,
            "currency":self.currency,"payload":self.payload,
            "lines":[{"product":x.canonical_product_id,"q":str(x.quantity),"p":str(x.unit_price),"uom":x.uom_id} for x in self.lines]},
            sort_keys=True,separators=(",",":"))
        return sha256(raw.encode()).hexdigest()

class ProjectionMappingStore(Protocol):
    def get(self,*,engine_instance_id:str,legal_entity_id:str,kind:str,canonical_id:str):...
    def put(self,*,engine_instance_id:str,legal_entity_id:str,kind:str,canonical_id:str,native_id:int,digest:str):...
