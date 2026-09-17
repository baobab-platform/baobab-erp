from decimal import Decimal
import pytest
from integration.trade_projection import *
def test_cross_boundary_identity_is_part_of_digest():
 a=TradeProjection("e","c","t","le-za","za","erp",TransactionKind.SALES_ORDER,"o1","bp","ZAR",
   (Line("p",Decimal("1"),Decimal("2"),"u"),),"v1",{})
 b=TradeProjection("e","c","t","le-ug","ug","erp",TransactionKind.SALES_ORDER,"o1","bp","UGX",
   (Line("p",Decimal("1"),Decimal("2"),"u"),),"v1",{})
 assert a.digest()!=b.digest()
def test_negative_quantity_rejected():
 p=TradeProjection("e","c","t","le","m","erp",TransactionKind.SALES_ORDER,"o","bp","ZAR",
  (Line("p",Decimal("-1"),Decimal("2"),"u"),),"v1",{})
 with pytest.raises(ProjectionError): p.validate()
