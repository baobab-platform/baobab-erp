"""Same-event observer negatives; fixture rows never establish a JVM effect."""
import copy
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev11_trade_persisted_jvm import PersistedTrade, private_run

EVENT={"id":"1d032305-669c-45df-b988-01166de4c14c",
 "source":"urn:baobab-platform:service:baobab-trade","tenantid":"tn_fixture",
 "idempotencykey":"fixture-event-key","correlationid":"2d032305-669c-45df-b988-01166de4c14c",
 "traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
 "data":{"commerce_order_id":"order_original_long_fixture"}}

class Rows:
 def __init__(self, rows):self.rows=rows
 def fetchall(self):return self.rows

class Source:
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def execute(self,sql,params=()):return Rows([("PUBLISHED",EVENT)])

class Erp:
 def __init__(self,changed):self.changed=changed
 def execute(self,sql,params):
  if "FROM baobab.event_inbox" in sql:
   row=[EVENT["id"],EVENT["source"],EVENT["tenantid"],copy.deepcopy(EVENT["data"]),
        EVENT["idempotencykey"],EVENT["correlationid"],EVENT["traceparent"],"processed"]
   if self.changed=="payload":row[3]["commerce_order_id"]="order_foreign"
   if self.changed=="event":row[0]="a-different-event"
   if self.changed=="trace":row[6]="a-different-trace"
   if self.changed=="status":row[7]="received"
   return Rows([tuple(row)])
  if self.changed=="missing-native":return Rows([])
  return Rows([(EVENT["id"],EVENT["data"]["commerce_order_id"],11,12 if self.changed=="native-id" else 11,11)])

class SameEventSafetyTests(unittest.TestCase):
 def test_child_failure_never_prints_private_command_or_event_ids(self):
  with tempfile.TemporaryDirectory() as root:
   for index,failure in enumerate((subprocess.TimeoutExpired(["private-event-id","private-bearer"],1),
                                   OSError("private-event-id private-bearer"))):
    with self.subTest(failure=type(failure).__name__),patch(
        "scripts.dev11_trade_persisted_jvm.subprocess.run",side_effect=failure):
     with self.assertRaises(RuntimeError) as raised:
      private_run(["private-event-id","private-bearer"],env={},cwd=root,
                  log=Path(root)/(str(index)+".log"),stage="PUBLISH")
     self.assertNotIn("private-",str(raised.exception))
     self.assertIn("PUBLISH",str(raised.exception))

 def test_changed_join_cannot_leave_a_success_receipt(self):
  bridge=PersistedTrade.__new__(PersistedTrade)
  bridge.database="unreachable-fixture-only"
  bridge.source=Path("unused-fixture-source")
  with tempfile.TemporaryDirectory() as root:
   out=Path(root)/"receipt.json"
   for changed in ("payload","event","trace","status","missing-native","native-id"):
    with self.subTest(changed=changed):
     out.write_text(json.dumps({"same_event_native_jvm_effect_joined":True}))
     with patch("scripts.dev11_trade_persisted_jvm.psycopg.connect",return_value=Source()),self.assertRaises(RuntimeError):
      bridge.verify_effect_join(Erp(changed),EVENT,out)
     self.assertFalse(out.exists())
