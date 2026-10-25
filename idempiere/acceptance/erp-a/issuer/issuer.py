#!/usr/bin/env python3
"""Baobab ERP-A harness test OIDC issuer (copied from the Payments Gate D1 harness). CI only, never deployed.

It stands in for IAM (a real Keycloak deployment is Gate D2) and issues real
RS256-signed JWTs that CP verifies exactly as in production: OIDC
discovery, a JWKS, issuer, audience, lifetime and claim checks.

  GET  /realms/baobab/.well-known/openid-configuration
  GET  /realms/baobab/certs
  POST /realms/baobab/token     client_credentials for registered workload
                                clients (form-encoded, secret checked)

Harness-only endpoints, reachable only on the published harness port and
never through the TLS front door:

  POST /_mint     mint a human administrator token or a calling workload token
  POST /_hold     hold the Nth next token request of one client
  GET  /_held     whether a request is being held
  POST /_release  release it
  GET  /_log      every token issued (client, scopes, jti), never the token
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

REALM = "/realms/baobab"
ISSUER = os.environ["ISSUER"]  # https://iam.gated.test/realms/baobab
KID = "erp-a-" + uuid.uuid4().hex[:8]
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
LIFETIME = 300

# Registered workload clients: id -> {secret, audience, scopes}.
with open(os.environ["CLIENTS_FILE"], encoding="utf-8") as _clients:
    CLIENTS: dict = json.load(_clients)

LOCK = threading.Lock()
LOG: list[dict] = []
HOLD = {"client": None, "skip": 0}
HELD = threading.Event()
RELEASE = threading.Event()


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwk() -> dict:
    numbers = KEY.public_key().public_numbers()
    to_bytes = lambda n: n.to_bytes((n.bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": KID,
            "n": b64(to_bytes(numbers.n)), "e": b64(to_bytes(numbers.e))}


def sign(claims: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": KID}
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    signature = KEY.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{b64(signature)}"


def issue(subject: str, audience: str, scopes: list[str], actor_type: str, client: str,
          extra: dict | None = None) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": subject, "aud": audience, "azp": client, "scope": " ".join(scopes),
              "actor_type": actor_type, "iat": now, "nbf": now, "exp": now + LIFETIME, "jti": str(uuid.uuid4())}
    claims.update(extra or {})
    with LOCK:
        LOG.append({"at": now, "client": client, "subject": subject, "actor_type": actor_type,
                    "audience": audience, "scopes": scopes, "jti": claims["jti"]})
    return sign(claims)


def maybe_hold(client: str) -> None:
    with LOCK:
        if HOLD["client"] != client:
            return
        if HOLD["skip"] > 0:
            HOLD["skip"] -= 1
            return
        HOLD["client"] = None
        RELEASE.clear()
        HELD.set()
    RELEASE.wait(timeout=60)
    HELD.clear()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> str:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length).decode() if length else ""

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == REALM + "/.well-known/openid-configuration":
            self.send_json(200, {
                "issuer": ISSUER, "jwks_uri": ISSUER + "/certs", "token_endpoint": ISSUER + "/token",
                "id_token_signing_alg_values_supported": ["RS256"],
                "grant_types_supported": ["client_credentials"],
                "response_types_supported": ["token"], "subject_types_supported": ["public"]})
            return
        if path == REALM + "/certs":
            self.send_json(200, {"keys": [jwk()]})
            return
        if path == "/_held":
            self.send_json(200, {"held": HELD.is_set()})
            return
        if path == "/_log":
            with LOCK:
                self.send_json(200, {"issued": LOG})
                return
        if path == "/_health":
            self.send_json(200, {"status": "UP"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        raw = self.body()
        # DEV-09 only: Hydra calls this over the private Compose network.
        # Hydra, not this fixture, signs actual ERP workload access tokens.
        # The separate test issuer remains for synthetic CP human admin setup.
        if path == "/_token_hook":
            expected = os.environ.get("ORY_HOOK_SECRET", "")
            supplied = self.headers.get("X-ERP-A-Hook-Key", "")
            if not expected or not hmac.compare_digest(expected, supplied) or len(raw) > 65536:
                self.send_json(403, {"error": "invalid_hook"})
                return
            try:
                body = json.loads(raw)
                request, session = body["request"], body["session"]
                client_id = request["client_id"]
                if (client_id not in CLIENTS or session["client_id"] != client_id
                        or request["grant_types"] != ["client_credentials"]
                        or session["id_token"]["subject"] != client_id):
                    raise ValueError("wrong client or grant")
            except (KeyError, TypeError, ValueError):
                self.send_json(403, {"error": "invalid_hook"})
                return
            self.send_json(200, {"session": {"access_token": {
                "actor_type": "workload", "azp": client_id}}})
            return
        if path == REALM + "/token":
            form = dict(parse_qsl(raw))
            client = CLIENTS.get(form.get("client_id", ""))
            if form.get("grant_type") != "client_credentials" or client is None or not hmac.compare_digest(
                    client["secret"].encode(), form.get("client_secret", "").encode()):
                self.send_json(401, {"error": "invalid_client"})
                return
            requested = form.get("scope", "").split()
            granted = [s for s in requested if s in client["scopes"]] or client["scopes"]
            maybe_hold(form["client_id"])
            token = issue(client.get("subject", form["client_id"]), client["audience"], granted, "workload",
                          form["client_id"])
            self.send_json(200, {"access_token": token, "token_type": "Bearer", "expires_in": LIFETIME})
            return
        request = json.loads(raw or "{}")
        if path == "/_mint":
            extra = {}
            if request["actor_type"] == "human":
                extra["realm_access"] = {"roles": request.get("roles", [])}
            token = issue(request["subject"], request["audience"], request["scopes"], request["actor_type"],
                          request.get("client", "erp-a-harness"), extra)
            self.send_json(200, {"access_token": token})
            return
        if path == "/_hold":
            with LOCK:
                HOLD.update(client=request["client"], skip=int(request.get("skip", 0)))
            self.send_json(200, {"armed": request})
            return
        if path == "/_release":
            RELEASE.set()
            self.send_json(200, {"released": True})
            return
        self.send_json(404, {"error": "not_found"})

    def log_message(self, fmt: str, *args) -> None:  # never echo tokens
        pass


def main() -> None:
    if os.environ.get("BAOBAB_ENVIRONMENT") != "integration":
        sys.exit("the ERP-A test issuer runs only with BAOBAB_ENVIRONMENT=integration")
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
