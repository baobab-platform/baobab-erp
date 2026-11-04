"""Disposable ERP-A orchestration of the EXISTING Trade outbox/publisher.

No messaging transport, event factory or business permission is implemented
here. Exact checked-out Trade code owns creation/export and publication; ERP
owns admission/execution; read-only observers join the same persisted event.
Synthetic fixture provenance stays explicit and never qualifies buyer origin.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import psycopg
from psycopg.rows import dict_row


def require(value, code):
    if not value:
        raise RuntimeError(code)


def exact_source(path, expected):
    require(re.fullmatch(r"[0-9a-f]{40}", expected or ""), "DEV11_EXACT_SOURCE_REQUIRED")
    actual=subprocess.check_output(["git","-C",str(path),"rev-parse","HEAD"],text=True).strip()
    require(actual == expected,"DEV11_EXECUTED_SOURCE_MISMATCH")


def private_run(command, *, env, cwd, log, timeout=240):
    # Child output can contain native diagnostic IDs. Keep it run-private;
    # only an allowlisted failure stage is ever exposed to CI logs.
    with open(log,"x",encoding="utf-8") as stream:
        os.chmod(log,0o600)
        result=subprocess.run(command,cwd=cwd,env=env,stdout=stream,stderr=stream,
                              timeout=timeout,check=False)
    require(result.returncode == 0,"DEV11_TRADE_SOURCE_OR_PUBLISHER_REFUSED")


class PersistedTrade:
    def __init__(self, run, state, compose, *, sku, unit, customer):
        self.run=run
        self.source=Path(os.environ["TRADE_SRC"])
        exact_source(self.source,os.environ["TRADE_COMMIT"])
        compose.run("--profile","dev11","up","-d","--wait",
                    "trade-db","trade-redis","jaeger","collector")
        self.database="postgresql://baobab_trade:"+os.environ["DEV11_TRADE_DB_PASSWORD"]+(
            "@127.0.0.1:55464/baobab_trade_jvm_test")
        self.env={**os.environ,"NODE_ENV":"test","BAOBAB_ENVIRONMENT":"development",
            "BAOBAB_DEPLOYMENT_ENV":"development","DATABASE_URL":self.database,
            "REDIS_URL":"redis://127.0.0.1:18379",
            "JWT_SECRET":"dev11-disposable-source-jwt",
            "COOKIE_SECRET":"dev11-disposable-source-cookie",
            "BAOBAB_WEBHOOK_SIGNING_SECRET":"dev11-disposable-source-signature",
            "BAOBAB_DEV11_JVM_COMPONENT_REQUIRED":"true",
            "BAOBAB_EVENT_DISPATCH_BACKEND":"rabbitmq-confirmed",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":"http://127.0.0.1:4318/v1/traces"}
        packet=run/"trade-fixture.private.json"
        with open(packet,"x",encoding="utf-8") as stream:
            os.chmod(packet,0o600)
            json.dump({"schema":"baobab.dev11.synthetic-jvm-source.v1",
                "tenant_id":state["tenant"],"legal_entity_id":state["legal_entity"],
                "customer_id":customer,"sku_id":sku,"unit":unit},stream)
        handoff=run/"trade-handoff.private.json"
        self.env.update({"BAOBAB_DEV11_JVM_INPUT":str(packet),
                         "BAOBAB_DEV11_JVM_HANDOFF":str(handoff)})
        private_run(["npm","run","migrate"],env=self.env,cwd=self.source,
                    log=run/"trade-migrate.private.log")
        private_run(["npm","run","qualify:dev11-jvm-prepare"],env=self.env,cwd=self.source,
                    log=run/"trade-source.private.log")
        receipt=json.loads(handoff.read_text())
        require(receipt.get("schema")=="baobab.dev11.persisted-trade-event-handoff.v1" and
                receipt.get("source_sha")==os.environ["TRADE_COMMIT"] and
                receipt.get("synthetic_business_input") is True and
                receipt.get("buyer_commitment_qualified") is False,
                "DEV11_TRADE_HANDOFF_PROVENANCE_INVALID")
        require(set(receipt.get("events",{}))=={"positive","ambiguous","denied"},
                "DEV11_TRADE_HANDOFF_EVENTS_MISSING")
        self.events={}
        with psycopg.connect(self.database,autocommit=True,row_factory=dict_row) as db:
            db.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for label,event_id in receipt["events"].items():
                rows=db.execute("""SELECT envelope FROM event_outbox
                    WHERE event_id=%s AND tenant_id=%s AND status='PENDING'
                    AND event_type='com.baobab-platform.trade.order.placed.v1'
                    AND deleted_at IS NULL""",(event_id,state["tenant"])).fetchall()
                require(len(rows)==1,"DEV11_ORIGINAL_TRADE_OUTBOX_NOT_UNIQUE")
                event=rows[0]["envelope"]
                require(event.get("id")==event_id and
                    event.get("source")=="urn:baobab-platform:service:baobab-trade" and
                    event.get("data",{}).get("legal_entity_id")==state["legal_entity"] and
                    len(event["data"]["commerce_order_id"])>20 and
                    re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01",event.get("traceparent","")),
                    "DEV11_ORIGINAL_EVENT_BINDING_INVALID")
                self.events[label]=event
            db.execute("COMMIT")
        # Keep the original provenance refusal. A real outbox and JVM effect
        # must not manufacture a governed Medusa buyer order.
        sys.path.insert(0,str(self.source/"scripts"))
        from dev11_native_business_origin import assess_native_origin
        with psycopg.connect(self.database,autocommit=True,row_factory=dict_row) as db:
            observed=assess_native_origin(db,self.events["positive"]["id"])
        require(not observed.qualified and observed.code=="NATIVE_ORDER_ABSENT",
                "DEV11_SYNTHETIC_SOURCE_NOT_EXPLICITLY_REFUSED")

    def publish(self, event, native_env):
        # The Trade dispatcher reads/signs the original outbox row itself.
        # No event envelope or fabricated success is passed as a callback.
        env={**self.env,"BAOBAB_RABBITMQ_URL":native_env["BAOBAB_RABBITMQ_URL"],
             "BAOBAB_EVENT_SIGNING_SECRET":native_env["BAOBAB_EVENT_SIGNING_SECRET"],
             "PYTHONPATH":str(self.source/"scripts")}
        private_run([sys.executable,"-B",str(self.source/"scripts/dev11_rabbit_dispatcher.py"),
                     "--max","1","--event-id",event["id"]],env=env,cwd=self.source,
                    log=self.run/("trade-publish-"+event["id"]+".private.log"))
        with psycopg.connect(self.database,autocommit=True) as db:
            rows=db.execute("SELECT status,envelope FROM event_outbox WHERE event_id=%s",
                            (event["id"],)).fetchall()
        require(len(rows)==1 and rows[0]==("PUBLISHED",event),
                "DEV11_ORIGINAL_OUTBOX_NOT_CONFIRMED_OR_CHANGED")

    def verify_effect_join(self, erp, event, output):
        # Independent immutable source readback, AFTER actual consumer/JVM
        # execution. Comparing payloads alone never establishes native effect:
        # the separate native order/CP-JVM verifier must also pass first.
        Path(output).unlink(missing_ok=True)
        with psycopg.connect(self.database,autocommit=True) as source:
            source.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            rows=source.execute("""SELECT status,envelope FROM event_outbox
                WHERE event_id=%s AND deleted_at IS NULL""",(event["id"],)).fetchall()
            source.execute("COMMIT")
        require(len(rows)==1 and rows[0]==("PUBLISHED",event),"DEV11_SOURCE_EVENT_NOT_PRESERVED")
        receipt=erp.execute("""SELECT event_id::text,ce_source,tenant_id,payload_json,
                ce_idempotency_key,ce_correlation_id::text,ce_traceparent,status
            FROM baobab.event_inbox WHERE event_id=%s::uuid""",(event["id"],)).fetchall()
        expected=(event["id"],event["source"],event["tenantid"],event["data"],
            event["idempotencykey"],event["correlationid"],event["traceparent"],"processed")
        require(len(receipt)==1 and receipt[0]==expected,"DEV11_SOURCE_TO_INBOX_IDENTITY_CHANGED")
        effects=erp.execute("""SELECT e.source_event_id::text,e.commerce_order_id,
                e.native_id,r.native_id,o.c_order_id
            FROM baobab.order_execution e
            JOIN baobab.order_native_reference r USING (tenant_id,legal_entity_id,commerce_order_id)
            JOIN adempiere.c_order o ON o.c_order_uu=r.native_uuid::text
            WHERE e.tenant_id=%s AND e.commerce_order_id=%s""",
            (event["tenantid"],event["data"]["commerce_order_id"])).fetchall()
        require(len(effects)==1 and effects[0][:2]==(event["id"],event["data"]["commerce_order_id"])
                and len(set(effects[0][2:]))==1,"DEV11_SAME_EVENT_NATIVE_EFFECT_NOT_JOINED")
        exact_source(self.source,os.environ["TRADE_COMMIT"])
        report={"schema":"baobab.dev11.persisted-trade-to-real-jvm.v1",
            "same_persisted_event_id":True,"unchanged_payload_correlation_and_traceparent":True,
            "real_trade_outbox_confirmed":True,"real_erp_inbox_execution":True,
            "lossless_full_order_native_uuid_join":True,"same_event_native_jvm_effect_joined":True,
            "native_buyer_origin_refusal":"NATIVE_ORDER_ABSENT",
            "source_pins":{"baobab-trade":os.environ["TRADE_COMMIT"],
                "baobab-erp":os.environ["ERP_COMMIT"],"infrastructure":os.environ["INFRA_COMMIT"],
                "baobab-cp":os.environ["CP_COMMIT"],"baobab-iam":os.environ["IAM_COMMIT"]},
            "full_medusa_buyer_commitment_proven":False,"l4_ops_01":"BLOCKED",
            "protected_acceptance":False}
        Path(output).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")

    def verify_exported_trace(self, event, output):
        source=Path(os.environ["INFRA_SRC"])
        exact_source(source,os.environ["INFRA_COMMIT"])
        trace_id=event["traceparent"].split("-")[1]
        # Independent observer queries real Jaeger; it never trusts stdout,
        # a stored traceparent, or the producer's own source-only graph.
        import time
        for _ in range(25):
            result=subprocess.run([sys.executable,"-B",str(source/"tests/platform-integration/development/dev11_exported_trace.py"),
                "--trace-id",trace_id,"--jaeger","http://127.0.0.1:16686",
                "--service","baobab-trade","--service","baobab-trade-rabbit-publisher",
                "--service","baobab-erp","--output",str(output)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=False)
            if result.returncode==0:return
            time.sleep(2)
        raise RuntimeError("DEV11_SAME_EVENT_EXPORTED_COMPONENT_TRACE_NOT_OBSERVED")
