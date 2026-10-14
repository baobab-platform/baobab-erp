#!/usr/bin/env python3
"""EA v2.1 Gate D — SYNTHETIC Control Plane and IAM over TLS. CI ONLY.

Serves the four routes the Baobab native finance veto calls, shaped exactly
like the pinned Shared contracts, so the REAL iDempiere posting path can be
exercised. It is not a CP, holds no mandate and is never evidence of legal
standing. The behaviour is selected by the text in <state>/mode:

  authorized        AUTHORIZED for the placement's legal entity
  no_mandate        NO_APPLICABLE_MANDATE
  revoked           REVOKED_OR_EXPIRED
  other_le          AUTHORIZED, but for another legal entity
  other_tenant      AUTHORIZED, but for another tenant
  wrong_market      AUTHORIZED, but for another market
  expired           AUTHORIZED, but its lease has already passed
  documentary_hold  AUTHORIZED, documentary restriction blocked
"""
import json
import os
import ssl
import sys
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

STATE = os.environ.get("GATE_D_STATE", "/state")
LE = os.environ.get("GATE_D_LEGAL_ENTITY", "SYNTHETIC-GATED-LE")
MARKET = os.environ.get("GATE_D_MARKET", "US")
CONTEXTS = {}
ACTIVITIES = {
    "erp.gl-journal.post": ("ACCOUNTING_ENTITY", "GENERAL_LEDGER_POSTING"),
    "erp.customer-invoice.issue": ("INVOICE_ISSUER", "CUSTOMER_INVOICE_ISSUANCE"),
    "erp.payment.record": ("ACCOUNTING_ENTITY", "PAYMENT_RECORDING"),
    "erp.allocation.record": ("ACCOUNTING_ENTITY", "PAYMENT_ALLOCATION"),
    "erp.shipment.complete": ("CONTRACTING_PARTY", "GOODS_DELIVERY"),
    "erp.sales-order.complete": ("CONTRACTING_PARTY", "SALES_ORDER_COMMITMENT"),
}


def now():
    return datetime.now(timezone.utc)


def stamp(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def mode():
    try:
        with open(os.path.join(STATE, "mode")) as f:
            return f.read().strip() or "authorized"
    except FileNotFoundError:
        return "authorized"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("synthetic-cp %s %s\n" % (mode(), fmt % args))

    def reply(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/token":
            form = parse_qs(raw.decode())
            if form.get("grant_type") != ["client_credentials"]:
                return self.reply({"error": "unsupported_grant_type"}, 400)
            return self.reply({"access_token": "synthetic-gate-d-token", "token_type": "Bearer", "expires_in": 300})
        if self.headers.get("Authorization") != "Bearer synthetic-gate-d-token":
            return self.reply({"error": "unauthenticated"}, 401)
        body = json.loads(raw or b"{}")
        if self.path == "/v1/platform-context/resolve":
            context = str(uuid.uuid4())
            CONTEXTS[context] = body
            t = now()
            return self.reply({
                "context_id": context, "tenant_id": body["tenant_id"],
                "resolved_at": stamp(t), "expires_at": stamp(t + timedelta(minutes=5)),
                "country_code": body["country_code"], "market_id": "mkt_" + body["country_code"].lower(),
                "currency_code": "USD", "organisation_id": body["organisation_id"],
                "organisation_type": "ORGANISATION"})
        if self.path == "/internal/erp/v1/posting-authority/resolve":
            return self.reply(self.decision(body))
        if self.path == "/internal/documentary/v1/restrictions/assess":
            scope = CONTEXTS.get(body["context_id"], {})
            t = now()
            return self.reply({
                "context_id": body["context_id"], "market": body["market"], "capability": body["capability"],
                "operation_reference": body["operation_reference"],
                "organisation_id": scope.get("organisation_id", str(uuid.uuid4())),
                "blocked": mode() == "documentary_hold", "authority_granted": False,
                "policy_reference": "ADR-BCP-026/PEO-02T:negative-only",
                "evaluated_at": stamp(t), "expires_at": stamp(t + timedelta(seconds=1))})
        return self.reply({"error": "not_found"}, 404)

    def decision(self, req):
        m = mode()
        scope = CONTEXTS.get(req["context_id"], {})
        role, activity = ACTIVITIES[req["operation_class"]]
        t = now()
        d = {
            "decision_id": str(uuid.uuid4()), "context_id": req["context_id"],
            "engine_instance_id": req["engine_instance_id"], "operation_class": req["operation_class"],
            "native_placement_reference": req["native_placement_reference"],
            "operation_reference": req["operation_reference"],
            "outcome": "AUTHORIZED", "tenant_id": scope.get("tenant_id", "tn_unknown01"),
            "operating_organisation_id": scope.get("organisation_id", str(uuid.uuid4())),
            "market": scope.get("country_code", MARKET), "legal_actor_role": role, "activity": activity,
            "evaluated_at": stamp(t), "policy_reference": "ADR-SHARED-034/erp-posting-authority:v1",
            "provider_permissions_granted": False}
        if m in ("no_mandate", "revoked"):
            d["outcome"] = "NO_APPLICABLE_MANDATE" if m == "no_mandate" else "REVOKED_OR_EXPIRED"
            return d
        d.update({
            "mandate_id": "7d2b9e4f-6a1c-4f3e-b8d5-0c9a8e7f6d21",
            "responsible_legal_entity_id": "OTHER-SYNTHETIC-LE" if m == "other_le" else LE,
            "evidence_references": ["synthetic:gate-d/mandate-evidence"],
            "mandate_effective_from": "2026-01-01T00:00:00Z",
            "expires_at": stamp(t + timedelta(seconds=25))})
        if m == "other_tenant":
            d["tenant_id"] = "tn_othertenant01"
        if m == "wrong_market":
            d["market"] = "ZA" if d["market"] != "ZA" else "UG"
        if m == "expired":
            d["evaluated_at"] = stamp(t - timedelta(seconds=40))
            d["expires_at"] = stamp(t - timedelta(seconds=15))
        return d


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(os.environ["GATE_D_CERT"], os.environ["GATE_D_KEY"])
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    print("synthetic CP/IAM listening on 8443 (CI only)", flush=True)
    server.serve_forever()
