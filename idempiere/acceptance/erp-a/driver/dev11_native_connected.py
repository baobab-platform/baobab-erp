#!/usr/bin/env python3
"""DEV-11 opt-in actual Hydra -> CP -> RabbitMQ -> ERP inbox -> protected JVM.

This runs only INSIDE the established ERP-A disposable iDempiere13 / Postgres17
acceptance stack, AFTER its real native JVM veto has been enabled. Creates
synthetic business fixture data but uses real Hydra client credentials, CP
binary/mandate assessment, RabbitMQ, ERP inbox/worker, and iDempiere's actual
native MOrder/MOrderLine code. Independent Postgres observers corroborate CP
immutable decisions, the JVM's native attribution and C_Order consequence.

This is NOT a real buyer's Medusa commitment, NOT independently verified
external legal identity and NOT full L4-OPS-01. It cannot be used in
staging/production; its evidence never asserts those qualifications.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import pika
import psycopg
from psycopg.rows import dict_row

from erpalib import CP, Compose, Evidence, call
from gate_d_erp_a import restore
from ory_bootstrap import CLIENT as HYDRA_CLIENT, HYDRA_PUBLIC, SCOPES, http

EVENT_TYPE = "com.baobab-platform.trade.order.placed.v1"
EXCHANGE = "baobab.trade.events.v1"
QUEUE = "baobab.erp.trade-order.v1"
DLX = "baobab.trade.dlx.v1"
DEAD = "baobab.erp.trade-order.dlq.v1"
ORDER_SOURCE = "urn:baobab-platform:service:baobab-trade"
PY_MODULES = str(Path(__file__).resolve().parents[4] / "modules")


def demand(ok, code):
    if not ok:
        raise RuntimeError(code)


def db_rows(db, sql, params=()):
    return db.execute(sql, params).fetchall()


def native_fixture(db):
    # Resolve the *same native GardenWorld fixture* as SalesFlow.order; never
    # guess a product by price/name on the business execution path.
    customer = db.execute(
        """SELECT min(bp.c_bpartner_id) FROM adempiere.c_bpartner bp
           WHERE bp.ad_client_id=11 AND bp.ad_org_id IN (0,11)
             AND bp.iscustomer='Y' AND bp.isactive='Y'
             AND EXISTS (SELECT 1 FROM adempiere.c_bpartner_location loc
                         WHERE loc.c_bpartner_id=bp.c_bpartner_id
                           AND loc.isactive='Y' AND loc.isbillto='Y'
                           AND loc.isshipto='Y')""").fetchone()[0]
    demand(type(customer) is int and customer > 0, "DEV11_NATIVE_CUSTOMER_NOT_READY")
    warehouse = db.execute(
        """SELECT min(m_warehouse_id) FROM adempiere.m_warehouse
           WHERE ad_client_id=11 AND ad_org_id=11 AND isactive='Y'""").fetchone()[0]
    demand(type(warehouse) is int and warehouse > 0, "DEV11_NATIVE_WAREHOUSE_NOT_READY")
    price_list = db.execute(
        """SELECT min(m_pricelist_id) FROM adempiere.m_pricelist
           WHERE ad_client_id=11 AND issopricelist='Y'
             AND isdefault='Y' AND isactive='Y'""").fetchone()[0]
    demand(type(price_list) is int and price_list > 0, "DEV11_NATIVE_SALES_PRICELIST_NOT_READY")
    product = db.execute(
        """SELECT min(p.m_product_id)
           FROM adempiere.m_product p
           WHERE p.ad_client_id=11 AND p.isstocked='Y'
             AND p.producttype='I' AND p.isactive='Y' AND p.issold='Y'
             AND EXISTS (
               SELECT 1 FROM adempiere.m_productprice pp
               JOIN adempiere.m_pricelist_version v
                 ON v.m_pricelist_version_id=pp.m_pricelist_version_id
              WHERE pp.m_product_id=p.m_product_id
                AND v.m_pricelist_id=%s AND pp.pricestd>0)
             AND EXISTS (
               SELECT 1 FROM adempiere.m_cost c
               JOIN adempiere.m_costelement ce
                 ON ce.m_costelement_id=c.m_costelement_id
              WHERE c.m_product_id=p.m_product_id
                AND ce.costingmethod='S' AND c.currentcostprice>0)
             AND (SELECT coalesce(sum(s.qtyonhand),0)
                  FROM adempiere.m_storageonhand s
                  JOIN adempiere.m_locator l ON l.m_locator_id=s.m_locator_id
                 WHERE s.m_product_id=p.m_product_id AND
                       l.m_warehouse_id=%s)>=10""",
        (price_list, warehouse)).fetchone()[0]
    # Each failure is a closed diagnostic category, never a guessed native ID
    # or a reason to loosen price/cost/stock predicates to force a positive.
    demand(type(product) is int and product > 0, "DEV11_NATIVE_SALEABLE_STOCK_NOT_READY")
    unit = db.execute(
        """SELECT u.x12de355 FROM adempiere.m_product p
           JOIN adempiere.c_uom u ON u.c_uom_id=p.c_uom_id
           WHERE p.m_product_id=%s""", (product,)).fetchone()[0]
    demand(isinstance(unit, str) and unit, "DEV11_NATIVE_PRODUCT_UOM_MISSING")
    return customer, product, unit


def hydrate_context(state, secret):
    status, token = http("POST", HYDRA_PUBLIC + "/oauth2/token", {
        "grant_type": "client_credentials", "client_id": HYDRA_CLIENT,
        "client_secret": secret, "scope": " ".join(SCOPES),
        "audience": "baobab-control-plane",
    }, form=True)
    demand(status == 200 and isinstance(token.get("access_token"), str),
           "DEV11_REAL_HYDRA_WORKLOAD_TOKEN_NOT_ISSUED")
    resolved = call("POST", CP + "/v1/platform-context/resolve", {
        "tenant_id": state["tenant"], "organisation_id": state["organisation"],
        "country_code": state["market"]}, {
        "Authorization": "Bearer " + token["access_token"],
    })
    demand(resolved.status == 200 and resolved.body["tenant_id"] == state["tenant"]
           and resolved.body["organisation_id"] == state["organisation"]
           and resolved.body["country_code"] == state["market"]
           and isinstance(resolved.body.get("context_id"), str),
           "DEV11_CP_RUNTIME_CONTEXT_NOT_ISSUED")
    return str(uuid.UUID(resolved.body["context_id"]))


def event_for(state, *, order, product_id, sku, unit, customer_key):
    from events.registry import dataschema_for
    event_id = str(uuid.uuid4())
    correlation = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": ORDER_SOURCE,
        "type": EVENT_TYPE,
        "subject": "order:" + order,
        "time": now,
        "datacontenttype": "application/json",
        "dataschema": dataschema_for(EVENT_TYPE),
        "baobabscope": "tenant",
        "tenantid": state["tenant"],
        "correlationid": correlation,
        "idempotencykey": "dev11-erp-a:" + event_id,
        # The source diagnostic context is synthetic here. A true end-to-end
        # OpenTelemetry lineage needs the separate real Medusa source run.
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "data": {
            "legal_entity_id": state["legal_entity"],
            "commerce_order_id": order, "order_version": 1,
            "customer_id": customer_key, "placed_at": now,
            "currency": "USD",
            "lines": [{
                "line_id": "line_dev11_real",
                "sku_id": sku, "quantity": {"value": "2", "unit": unit},
                "unit_price": {"amount": "10.00", "currency": "USD"},
                "line_total": {"amount": "20.00", "currency": "USD"},
            }],
            "totals": {
                "subtotal": {"amount": "20.00", "currency": "USD"},
                "discount": {"amount": "0.00", "currency": "USD"},
                "quoted_tax": {"amount": "0.00", "currency": "USD"},
                "grand_total": {"amount": "20.00", "currency": "USD"},
            },
        },
    }


def bind_native(db, state, *, customer_id, product_id, sku, customer_key):
    with db.transaction():
        db.execute(
            """INSERT INTO baobab.tenant_mapping
                    (tenant_id,entity_id,engine_instance_id,ad_client_id,ad_org_id,status)
               VALUES (%s,%s,%s,11,11,'active')""",
            (state["tenant"], state["legal_entity"], state["engine_instance"]))
        for kind, canonical, native in (
                ("business_partner", customer_key, customer_id),
                ("product", sku, product_id)):
            db.execute(
                """INSERT INTO baobab.erp_master_data_mapping
                   (engine_instance_id,legal_entity_id,resource_kind,
                    canonical_id,native_id,desired_digest,source_version)
                   VALUES (%s,%s,%s,%s,%s,'dev11-synthetic-fixture','dev11-integration-v1')""",
                (state["engine_instance"],state["legal_entity"],kind,canonical,native))


def operator_file(run, state, context_id, events):
    entries = []
    for event in events:
        entries.append({
            "event_id": event["id"], "source": event["source"],
            "tenant_id": state["tenant"], "idempotency_key": event["idempotencykey"],
            "commerce_order_id": event["data"]["commerce_order_id"],
            "legal_entity_id": state["legal_entity"],
            "context_id": context_id,
            "operating_organisation_id": state["organisation"],
            "market": state["market"], "activity": "SALES_ORDER_COMMITMENT",
            # CP seed's actual baobab-erp scoped capability. No invented
            # authority follows from this local registry or event.
            "capability": "erp.erp-a",
            "authority_reference": "synthetic:erp-a/dev11-native-order-v1",
            "engine_instance_id": state["engine_instance"],
            "ad_client_id": 11, "ad_org_id": 11,
            "finance_baseline_version": 1,
        })
    path = run / "dev11-operator-authority.json"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"schema": "baobab.erp.dev11.operator-authority.v1",
                   "entries": entries}, stream)
    return path


def launch_consumer(base_env):
    return subprocess.Popen(
        [sys.executable, "-B", "-m", "application.amqp_consumer"],
        env=base_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def send(channel, event, signing_key):
    body = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    signature = "sha256=" + hmac.new(signing_key.encode(), body, hashlib.sha256).hexdigest()
    channel.basic_publish(
        exchange=EXCHANGE, routing_key=EVENT_TYPE, body=body, mandatory=True,
        properties=pika.BasicProperties(
            content_type="application/cloudevents+json", delivery_mode=2,
            message_id=event["id"], type=EVENT_TYPE,
            headers={"x-baobab-signature": signature}))


def await_inbox(db, event_id):
    for _ in range(100):
        row = db.execute(
            "SELECT status FROM baobab.event_inbox WHERE event_id=%s::uuid",
            (event_id,)).fetchone()
        if row:
            return row[0]
        time.sleep(.2)
    raise RuntimeError("DEV11_REAL_RABBIT_ERP_INBOX_NOT_ADMITTED")


def worker_once(env):
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "application.inbox_worker"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=240, check=False)
    demand(completed.returncode == 0, "DEV11_REAL_NATIVE_ERP_WORKER_FAILED")


def inspect_outcome(db, event_id, *, allowed):
    row = db.execute(
        "SELECT status,outcome_code FROM baobab.event_inbox WHERE event_id=%s::uuid",
        (event_id,)).fetchone()
    demand(row is not None, "DEV11_NATIVE_INBOX_OUTCOME_UNOBSERVED")
    status, code = row
    if allowed:
        demand(status == "processed" and code in ("EXECUTED", "ADOPTED_NATIVE_ORDER"),
               "DEV11_REAL_NATIVE_ORDER_NOT_EXECUTED")
    else:
        demand(status in ("blocked","retry","dead_letter") and
               code not in ("EXECUTED","ADOPTED_NATIVE_ORDER"),
               "DEV11_REVOKED_ORDER_WAS_UNEXPECTEDLY_EXECUTED")
    return code


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--compose",required=True)
    args=parser.parse_args()
    if (os.environ.get("BAOBAB_ENVIRONMENT")!="integration"
            or os.environ.get("DEV11_REAL_NATIVE_ACCEPTANCE")!="true"):
        raise RuntimeError("DEV11_REAL_NATIVE_DISPOSABLE_PROFILE_REQUIRED")
    run, out = args.run, args.out
    demand((run/"gate-d"/"ready").exists(), "DEV11_IDEMPIERE_JVM_NOT_READY")
    compose=Compose(args.compose)
    # Verify the native veto marker inside the actual JVM, not a caller's
    # environment variable. An unprotected JVM is NEVER qualifying.
    compose.run("exec","-T","erp","test","-s",
                "/opt/idempiere/.baobab/native-finance-veto-active")
    evidence=Evidence(str(out))
    cp,state=restore(args,compose,evidence)
    demand(state["market"]=="US" and state["legal_entity"]=="LE-ERPAUS",
           "DEV11_GARDENWORLD_FIXTURE_SCOPE_INVALID")
    sales_mandate=cp.propose(
        {"roles":["CONTRACTING_PARTY"],
         "activities":["SALES_ORDER_COMMITMENT"]},
        "erp-a/dev11-synthetic-sales-mandate")
    cp.mandate=sales_mandate
    secret=os.environ["ERP_WORKLOAD_SECRET"]
    context_id=hydrate_context(state,secret)
    erp_url="postgresql://adempiere:adempiere@127.0.0.1:55462/idempiere"
    native_env={**os.environ,
        "PYTHONPATH":PY_MODULES + os.pathsep
                     + str(Path(__file__).resolve().parents[4] / "scripts"),
        "DATABASE_URL":erp_url,
        "ERP_DATABASE_URL":erp_url,
        "ERP_NATIVE_DATABASE_URL":erp_url,
        "CP_DATABASE_URL":"postgresql://controlplane:"
            + os.environ["CPDB_PASSWORD"] + "@127.0.0.1:55463/controlplane",
        "BAOBAB_ENVIRONMENT":"integration",
        "BAOBAB_DEPLOYMENT_ENV":"integration",
        "BAOBAB_ERP_INBOX_PROFILE":"dev11-order-placed",
        "BAOBAB_REQUIRE_LEGAL_ACTOR_GATE":"true",
        "BAOBAB_DEV11_REAL_JVM_GATE_ENABLED":"true",
        "BAOBAB_DEV11_GARDENWORLD_US_FIXTURE":"true",
        "BAOBAB_DEV11_ENGINE_DRIVER_DIR":str(run/"gate-d"),
        "BAOBAB_DEV11_ENGINE_NATIVE_DATABASE_URL":erp_url,
        "BAOBAB_ERP_CP_URL":"http://localhost:18092",
        "BAOBAB_ERP_CP_OAUTH_TOKEN_URL":"http://127.0.0.1:18015/oauth2/token",
        "BAOBAB_ERP_CP_WORKLOAD_CLIENT_ID":HYDRA_CLIENT,
        "BAOBAB_ERP_CP_WORKLOAD_SECRET_FILE":str(run/"erp-secret"/"workload-secret"),
    }
    with psycopg.connect(erp_url,autocommit=True) as db:
        customer,product,unit=native_fixture(db)
        customer_key="customer_dev11_synthetic"
        sku="sku_dev11_synthetic"
        bind_native(db,state,customer_id=customer,product_id=product,
                    sku=sku,customer_key=customer_key)
        positive=event_for(state,order="order_dev11_"+uuid.uuid4().hex,
                           product_id=product,sku=sku,unit=unit,
                           customer_key=customer_key)
        ambiguous=event_for(state,order="order_dev11_unknown_"+uuid.uuid4().hex,
                            product_id=product,sku=sku,unit=unit,
                            customer_key=customer_key)
        denied=event_for(state,order="order_dev11_revoked_"+uuid.uuid4().hex,
                         product_id=product,sku=sku,unit=unit,
                         customer_key=customer_key)
        registry=operator_file(run,state,context_id,(positive,ambiguous,denied))
        native_env["BAOBAB_ERP_INBOX_AUTHORITY_REGISTRY_FILE"]=str(registry)

        password=secrets.token_hex(20)
        os.environ["DEV11_RABBIT_PASSWORD"]=password
        compose.run("--profile","dev11","up","-d","--wait","rabbitmq")
        url="amqp://dev11:"+quote(password,safe="")+"@127.0.0.1:15673/%2F"
        native_env["BAOBAB_RABBITMQ_URL"]=url
        native_env["BAOBAB_EVENT_SIGNING_SECRET"]=secrets.token_hex(32)
        broker=pika.BlockingConnection(pika.URLParameters(url))
        receiver=None
        try:
            channel=broker.channel()
            channel.exchange_declare(exchange=EXCHANGE,exchange_type="topic",durable=True)
            channel.exchange_declare(exchange=DLX,exchange_type="direct",durable=True)
            channel.queue_declare(queue=QUEUE,durable=True,arguments={
                "x-queue-type":"quorum","x-dead-letter-exchange":DLX,
                "x-dead-letter-routing-key":"invalid"})
            channel.queue_declare(queue=DEAD,durable=True,arguments={"x-queue-type":"quorum"})
            channel.queue_bind(queue=QUEUE,exchange=EXCHANGE,routing_key=EVENT_TYPE)
            channel.queue_bind(queue=DEAD,exchange=DLX,routing_key="invalid")
            channel.confirm_delivery()
            receiver=launch_consumer(native_env)
            time.sleep(1)
            demand(receiver.poll() is None,"DEV11_REAL_ERP_RABBIT_CONSUMER_STARTUP_FAILED")

            send(channel,positive,native_env["BAOBAB_EVENT_SIGNING_SECRET"])
            await_inbox(db,positive["id"])
            worker_once(native_env)
            inspect_outcome(db,positive["id"],allowed=True)
            # Real independent processes re-read persisted native C_Order, CP
            # immutable history and actual JVM attribution; neither script
            # trusts this producer's success assertion.
            common=[
                "--tenant",state["tenant"],
                "--legal-entity",state["legal_entity"],
                "--ad-client","11","--ad-org","11"]
            verify_native=[
                sys.executable,"-B",
                str(Path(__file__).resolve().parents[4] /
                    "scripts/dev11_verify_native_idempiere_order.py"),
                *common,"--event-id",positive["id"],
                "--output",str(out/"dev11-native-effect.json")]
            subprocess.run(verify_native,env=native_env,check=True,timeout=45)
            verify_cp=[
                sys.executable,"-B",
                str(Path(__file__).resolve().parents[4] /
                    "scripts/dev11_verify_cp_native_lineage.py"),
                *common,"--commerce-order",positive["data"]["commerce_order_id"],
                "--market",state["market"],
                "--output",str(out/"dev11-cp-jvm-lineage.json")]
            subprocess.run(verify_cp,env=native_env,check=True,timeout=45)

            # A signed broker redelivery is not a second native order.
            send(channel,positive,native_env["BAOBAB_EVENT_SIGNING_SECRET"])
            for _ in range(30):
                if (channel.queue_declare(queue=QUEUE,passive=True)
                           .method.message_count == 0):
                    break
                time.sleep(.2)
            count=db.execute(
                "SELECT count(*) FROM adempiere.c_order WHERE poreference=%s",
                (positive["data"]["commerce_order_id"],)).fetchone()[0]
            demand(count==1,"DEV11_REAL_BROKER_REDELIVERY_CREATED_EXTRA_NATIVE_ORDER")

            # Native unknown-outcome recovery: the REAL protected JVM
            # commits a separate exact C_Order, but the ERP worker injects a
            # loss of its own application result AFTER independent readback.
            # Retry may ONLY adopt the same native order and immutable facts.
            send(channel,ambiguous,native_env["BAOBAB_EVENT_SIGNING_SECRET"])
            await_inbox(db,ambiguous["id"])
            worker_once({**native_env,
                         "BAOBAB_DEV11_NATIVE_UNKNOWN_AFTER_COMMIT":"true"})
            inspect_outcome(db,ambiguous["id"],allowed=False)
            before_replay=db.execute(
                "SELECT count(*) FROM adempiere.c_order WHERE poreference=%s",
                (ambiguous["data"]["commerce_order_id"],)).fetchone()[0]
            demand(before_replay==1,"DEV11_REAL_JVM_UNKNOWN_COMMIT_NOT_OBSERVED")
            ready=False
            for _ in range(160):
                row=db.execute(
                    """SELECT status,next_attempt_at <= now()
                       FROM baobab.event_inbox WHERE event_id=%s::uuid""",
                    (ambiguous["id"],)).fetchone()
                ready=bool(row and row[0]=="retry" and row[1])
                if ready: break
                time.sleep(.25)
            demand(ready,"DEV11_NATIVE_UNKNOWN_OUTCOME_NOT_RETRYABLE")
            worker_once(native_env)
            recovered=inspect_outcome(db,ambiguous["id"],allowed=True)
            demand(recovered=="ADOPTED_NATIVE_ORDER",
                   "DEV11_REAL_JVM_UNKNOWN_OUTCOME_NOT_ADOPTED")
            after_replay=db.execute(
                "SELECT count(*) FROM adempiere.c_order WHERE poreference=%s",
                (ambiguous["data"]["commerce_order_id"],)).fetchone()[0]
            demand(after_replay==1,"DEV11_NATIVE_UNKNOWN_RETRY_DUPLICATED_ORDER")
            native_receipt=Path(__file__).resolve().parents[4] / (
                "scripts/dev11_verify_native_idempiere_order.py")
            subprocess.run([
                sys.executable,"-B",str(native_receipt),
                *common,"--event-id",ambiguous["id"],
                "--output",str(out/"dev11-native-unknown-adopted.json")],
                env=native_env,check=True,timeout=45)

            # LIVE CP revocation, not a Python boolean. Re-use the now-invalid
            # CP-minted context to demonstrate it is not a permanent mandate.
            cp.revoke(sales_mandate)
            send(channel,denied,native_env["BAOBAB_EVENT_SIGNING_SECRET"])
            await_inbox(db,denied["id"])
            worker_once(native_env)
            inspect_outcome(db,denied["id"],allowed=False)
            no_order=db.execute(
                "SELECT count(*) FROM adempiere.c_order WHERE poreference=%s",
                (denied["data"]["commerce_order_id"],)).fetchone()[0]
            demand(no_order==0,"DEV11_REVOKED_REAL_NATIVE_ORDER_COMMITTED")
            report={
                "schema":"erp.dev11.real-hydra-cp-rabbit-jvm-engine-local.v1",
                "source_pins":{
                    "baobab-cp":os.environ["CP_COMMIT"],
                    "baobab-iam":os.environ["IAM_COMMIT"],
                    "baobab-erp":os.environ["ERP_COMMIT"]},
                "real_hydra_workload_token_observed":True,
                "real_cp_runtime_context_and_mandate_observed":True,
                "real_rabbitmq_durable_signed_event_to_erp_inbox":True,
                "real_cp_authorized_idempiere_jvm_sales_order":True,
                "independent_native_order_and_cp_lineage_readback":True,
                "real_live_cp_mandate_revocation_denied_next_order":True,
                "real_broker_redelivery_one_native_order":True,
                "real_jvm_committed_then_worker_outcome_lost_and_adopted":True,
                "synthetic_trade_origin_not_authorized_commitment":True,
                "full_medusa_buyer_commitment_proven":False,
                "independent_exported_trace_graph_proven":False,
                "l4_ops_01":"BLOCKED",
                "protected_acceptance":False,
                "staging_authorized":False,
                "production_authorized":False}
            (out/"dev11-engine-local.json").write_text(
                json.dumps(report,sort_keys=True,indent=2)+"\n")
            print("DEV11_REAL_IAM_CP_TO_IDEMPIERE_ENGINE_LOCAL_PASS; FULL_L4_BLOCKED")
        finally:
            if receiver is not None and receiver.poll() is None:
                receiver.terminate()
                try: receiver.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    receiver.kill();receiver.wait(timeout=5)
            if broker.is_open:
                broker.close()
            registry.unlink(missing_ok=True)


if __name__=="__main__":
    main()
