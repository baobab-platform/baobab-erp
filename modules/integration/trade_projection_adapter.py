from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol
from integration.trade_projection import ProjectionMappingStore, TradeProjection, TransactionKind
from provisioning.master_data_mapping import MasterDataMappingStore

TABLE={
 TransactionKind.PROCUREMENT_ORDER:"C_Order",
 TransactionKind.SALES_ORDER:"C_Order",
 TransactionKind.GOODS_RECEIPT:"M_InOut",
 TransactionKind.SHIPMENT:"M_InOut",
 TransactionKind.AP_INVOICE:"C_Invoice",
 TransactionKind.AR_INVOICE:"C_Invoice",
 TransactionKind.AP_PAYMENT:"C_Payment",
 TransactionKind.AR_PAYMENT:"C_Payment",
}

# C_Order and M_InOut are shared between the sales and purchase side of iDempiere's
# native schema, distinguished only by IsSOTrx; C_Payment is distinguished by
# IsReceipt. Neither has a sales-safe default, so every kind that reaches one of
# these shared tables must set its flag explicitly -- leaving it to iDempiere's
# column default would silently misclassify a purchase-side document as sales-side.
_SALES_SIDE = frozenset({TransactionKind.SALES_ORDER, TransactionKind.AR_INVOICE, TransactionKind.SHIPMENT})
_PURCHASE_SIDE = frozenset({TransactionKind.PROCUREMENT_ORDER, TransactionKind.AP_INVOICE, TransactionKind.GOODS_RECEIPT})


class TradeIdempiereClient(Protocol):
    def get_record(self, table: str, record_id: int) -> dict[str, Any]: ...
    def create_record(self, table: str, fields: dict[str, Any]) -> int: ...


@dataclass(slots=True)
class IdempiereTradeProjectionAdapter:
    """Projects a Trade-owned commercial fact into its native iDempiere header record.

    Financial projections are immutable by default (per ADR-ERP-008's posted-record
    invariants): a canonical_transaction_id already mapped to a native record whose
    digest has since changed raises rather than silently mutating the native record --
    an explicit correction/reversal workflow is required, not built here.
    """
    client: TradeIdempiereClient
    mappings: ProjectionMappingStore
    master_mappings: MasterDataMappingStore

    def project(self,p:TradeProjection)->dict:
        p.validate(); digest=p.digest()
        mapped=self.mappings.get(engine_instance_id=p.engine_instance_id,legal_entity_id=p.legal_entity_id,
                                 kind=p.kind.value,canonical_id=p.canonical_transaction_id)
        if mapped:
            native_id,old_digest=mapped
            self.client.get_record(TABLE[p.kind],native_id)
            if old_digest != digest:
                raise ValueError("financial transaction projection changed after creation; explicit correction flow required")
            return {"native_id":native_id,"reused":True}
        fields=self._header(p)
        native_id=self.client.create_record(TABLE[p.kind],fields)
        self.mappings.put(engine_instance_id=p.engine_instance_id,legal_entity_id=p.legal_entity_id,
                          kind=p.kind.value,canonical_id=p.canonical_transaction_id,native_id=native_id,digest=digest)
        return {"native_id":native_id,"reused":False}

    def _header(self,p):
        bp=self.master_mappings.get(engine_instance_id=p.engine_instance_id,legal_entity_id=p.legal_entity_id,
                                    kind="business_partner",canonical_id=p.counterparty_id)
        if not bp: raise ValueError("counterparty has no ERP mapping")
        fields={"DocumentNo":p.canonical_transaction_id,"C_BPartner_ID":bp[0],
                "Description":f"Baobab correlation {p.correlation_id}","IsActive":True,
                **dict(p.payload)}
        if p.kind in _SALES_SIDE:
            fields["IsSOTrx"] = True
        elif p.kind in _PURCHASE_SIDE:
            fields["IsSOTrx"] = False
        elif p.kind is TransactionKind.AR_PAYMENT:
            fields["IsReceipt"] = True
        elif p.kind is TransactionKind.AP_PAYMENT:
            fields["IsReceipt"] = False
        return fields
