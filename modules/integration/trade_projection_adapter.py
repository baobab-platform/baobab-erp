from dataclasses import dataclass
from integration.trade_projection import TradeProjection, TransactionKind

TABLE={
 TransactionKind.PROCUREMENT_ORDER:"C_Order",
 TransactionKind.SALES_ORDER:"C_Order",
 TransactionKind.GOODS_RECEIPT:"M_InOut",
 TransactionKind.SHIPMENT:"M_InOut",
 TransactionKind.AP_INVOICE:"C_Invoice",
 TransactionKind.AR_INVOICE:"C_Invoice",
 TransactionKind.PAYMENT:"C_Payment",
}

@dataclass(slots=True)
class IdempiereTradeProjectionAdapter:
    client:object
    mappings:object
    master_mappings:object

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
        return {"DocumentNo":p.canonical_transaction_id,"C_BPartner_ID":bp[0],
                "Description":f"Baobab correlation {p.correlation_id}","IsActive":True,
                **dict(p.payload)}
