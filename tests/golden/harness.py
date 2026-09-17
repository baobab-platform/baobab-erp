from dataclasses import dataclass
@dataclass(slots=True)
class GoldenHarness:
    trade:object
    erp:object
    reconciliation:object

    def procurement(self,ctx,fixture):
        po=self.trade.create_procurement(ctx,fixture)
        receipt=self.erp.receive(ctx,po)
        invoice=self.erp.supplier_invoice(ctx,receipt)
        payment=self.erp.pay_supplier(ctx,invoice)
        return self.reconciliation.assert_balanced(ctx,[po,receipt,invoice,payment])

    def sales(self,ctx,fixture):
        order=self.trade.create_sales_order(ctx,fixture)
        shipment=self.erp.ship(ctx,order)
        invoice=self.erp.customer_invoice(ctx,shipment)
        payment=self.erp.receive_payment(ctx,invoice)
        return self.reconciliation.assert_balanced(ctx,[order,shipment,invoice,payment])

    def inventory(self,ctx,fixture):
        movement=self.erp.inventory_flow(ctx,fixture)
        return self.reconciliation.assert_inventory(ctx,movement)

    def fx(self,ctx,fixture):
        tx=self.erp.foreign_currency_flow(ctx,fixture)
        return self.reconciliation.assert_fx(ctx,tx)
