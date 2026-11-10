"""Recovery-coordinate regressions; SQL/authority fixtures are not JVM evidence."""
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import uuid

from integration.idempiere_client import IdempiereClientError
from order_to_cash.native_reference import (
    NativeOrderReference, bind_native, matches_governed_reference,
    reserve, using_reference,
)

NATIVE_UUID = "15be9a37-3545-4cdf-8f20-842b4c84f771"


class ReferenceTests(unittest.TestCase):
    def fixture(self, *, changed=False):
        order = SimpleNamespace(legal_entity_id="LE-TEST", commerce_order_id="order_" + "a" * 120,
                                order_version=1)
        claim = SimpleNamespace(tenant_id="tn_fixture", event_id=str(uuid.uuid4()),
            data={"commerce_order_id":order.commerce_order_id,"currency":"USD"})
        target = SimpleNamespace(engine_instance_id="ei_fixture",ad_client_id=11,ad_org_id=11)
        digest = "sha256:" + hashlib.sha256(json.dumps(claim.data, sort_keys=True,
            separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchone.return_value=("ei_fixture",11,12 if changed else 11,1,digest,NATIVE_UUID,None)
        cursor.rowcount=1
        db=Mock();db.cursor.return_value=cursor
        return db,cursor,claim,order,target

    def test_full_canonical_key_survives_reservation_and_native_uuid_is_separate(self):
        db,cursor,claim,order,target=self.fixture()
        reference=reserve(db,claim,order,target)
        self.assertEqual(reference.commerce_order_id, order.commerce_order_id)
        self.assertEqual(len(reference.commerce_order_id),126)
        self.assertEqual(reference.native_uuid,NATIVE_UUID)
        self.assertFalse(reference.attempted)
        self.assertIn(order.commerce_order_id,cursor.execute.call_args_list[0].args[1])
        db.commit.assert_called_once()

    def test_foreign_scope_never_reuses_an_existing_coordinate(self):
        db,_,claim,order,target=self.fixture(changed=True)
        with self.assertRaisesRegex(IdempiereClientError,"SCOPE_OR_FACTS_CHANGED"):
            reserve(db,claim,order,target)
        db.commit.assert_not_called()

    def test_mapping_is_no_authority_and_requires_the_exact_existing_governed_marker(self):
        reference=NativeOrderReference("tn_fixture","LE-TEST","order_long_original",
            "ei_fixture",11,11,NATIVE_UUID,False)
        marker=("tn_fixture","LE-TEST","create_sales_order","order_long_original",11,11)
        body={"C_Order_UU":NATIVE_UUID}
        self.assertFalse(matches_governed_reference(marker,body))
        with using_reference(reference):
            self.assertTrue(matches_governed_reference(marker,body))
            for changed in (None,(*marker[:-1],12),(*marker[:3],"order_other",11,11)):
                self.assertFalse(matches_governed_reference(changed,body))
            self.assertFalse(matches_governed_reference(marker,{**body,"POReference":"short"}))
            self.assertFalse(matches_governed_reference(marker,{"C_Order_UU":str(uuid.uuid4())}))
        self.assertFalse(matches_governed_reference(marker,body))

    def test_invalid_or_missing_native_settlement_does_not_commit_a_mapping(self):
        db,cursor,_,_,_=self.fixture()
        reference=NativeOrderReference("tn_fixture","LE-TEST","order_original",
            "ei_fixture",11,11,NATIVE_UUID,True)
        for value in (True,0,-1,2**31,1.1,"11"):
            with self.assertRaises(IdempiereClientError):bind_native(db,reference,value)
        cursor.rowcount=0
        with self.assertRaisesRegex(IdempiereClientError,"BINDING_CHANGED"):
            bind_native(db,reference,11)
        db.commit.assert_not_called()
