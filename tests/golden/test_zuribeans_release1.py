import os, pytest
pytestmark=pytest.mark.skipif(os.getenv("RUN_IDEMPIERE_GOLDEN")!="1",
 reason="requires provisioned test iDempiere and Baobab integration stack")

def test_za_and_ug_are_executed_as_distinct_legal_entities(golden,za_context,ug_context,fixtures):
    assert za_context.legal_entity_id != ug_context.legal_entity_id
    assert golden.procurement(ug_context,fixtures.ug_procurement)
    assert golden.sales(za_context,fixtures.za_sale)
    assert golden.inventory(ug_context,fixtures.ug_inventory)
    assert golden.fx(za_context,fixtures.za_fx)

def test_reverse_market_capability_is_not_hard_coded(golden,za_context,ug_context,fixtures):
    assert golden.procurement(za_context,fixtures.za_procurement)
    assert golden.sales(ug_context,fixtures.ug_sale)
