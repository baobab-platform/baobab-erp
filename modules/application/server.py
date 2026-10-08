"""Minimal HTTP application layer: liveness/readiness probes, the inbound
signed-event webhook receiver, context/mapping resolution for the OSGi bundles
in idempiere/extensions (they run inside iDempiere's own JVM and have no direct
access to the baobab Postgres schema; this is how they reach it), the outbox
recording endpoint those same bundles' OutboxPublisher calls, and the sell-side
order-to-cash command surface (ADR-ERP-016) Commerce calls into. Deliberately
stdlib-only (http.server) rather than a web framework -- no ADR has chosen one yet,
and this surface doesn't need one. A framework choice is tracked in
architecture/conformance.yaml against ADR-ERP-005 if/when the surface grows past
this.

Each request opens its own short-lived Postgres connection: psycopg connections
are not safe to share across the threads ThreadingHTTPServer uses for concurrent
requests. A `with psycopg.connect(...) as connection:` block commits on normal
exit and rolls back on exception (psycopg3's own connection-context-manager
behaviour), which is how the order-to-cash endpoints get the "mapping write and
outbox write commit or roll back together" guarantee order_to_cash.service's own
docstring documents -- both live in this one call's one connection/transaction.

/context/resolve*, /mapping/resolve*, /outbox/record, and every order-to-cash
command endpoint require a Baobab IAM-issued workload bearer token
(actor_type=workload, aud=baobab-erp, ADR-0014 §111) -- see
security.workload_auth. They no longer rely on network-level trust alone,
closing the gap this module's own docstring used to note here (ADR-ERP-010).

Each of those paths also requires its token to carry a specific scope
(_WORKLOAD_REQUIRED_SCOPES) -- a validly authenticated workload whose token
doesn't grant that scope gets 403, not access. This closes the gap
architecture/conformance.yaml's ADR-ERP-010 block used to record here:
Gate IAM-10 phase 2 authenticated callers but let any valid workload token
call every gated endpoint regardless of scope. Every order-to-cash and outbox
path requires the same erp:integrate scope as /context/resolve*/mapping/resolve*
today, for the same reason PR ZB-03.8 gives there: it is the only scope granted
to any workload client so far (baobab-iam/config/scopes/erp-integrate.json).

The order-to-cash endpoints need two pieces of deployment configuration this
module cannot invent: per-AD_Client iDempiere REST credentials (there is no live
iDempiere instance in any environment this code has run in yet -- see
integration.idempiere_client's own docstring) and the native process IDs
order_to_cash.service.ProcessIds needs (iDempiere assigns these per
installation). Both are optional at startup -- unlike DATABASE_URL/
BAOBAB_EVENT_SIGNING_SECRET/BAOBAB_IAM_OIDC_ISSUER below, an unconfigured
order-to-cash surface must not take down health/context/mapping, which have
worked, and been relied on, since before this surface existed. An order-to-cash
request against an unconfigured AD_Client gets a clear 503, not a crash.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import psycopg

from application import boundary
from application.health import liveness, readiness
from application.problem import correlation_id_from, kind_for_status, problem, trace_id_from
from application.provisioning_operations import MAX_BODY_BYTES, RETRY_AFTER_SECONDS as CONTEXT_RETRY_AFTER_SECONDS, ProvisioningDependencies
from context.model import ContextResolutionError
from context.postgres_store import PostgresTenantMappingStore
from context.resolver import resolve_context, resolve_tenant
from events.envelope import EventEnvelope
from inbox.postgres_store import PostgresInboxStore
from inbox.service import InvalidSignatureError, receive
from integration.idempiere_client import IdempiereCredentials, IdempiereClientError, RestIdempiereClient, UnconfiguredIdempiereClient, IdempiereEndpoint
from mapping.model import MappingNotFoundError
from mapping.postgres_store import PostgresCanonicalMappingStore
from mapping.resolver import resolve_to_canonical, resolve_to_native
from order_to_cash import service as order_to_cash
from order_to_cash.consequence_store import PostgresOrderConsequenceStore
from order_to_cash.outcome_store import PostgresDocumentOutcomeStore
from order_to_cash.model import OrderLine, OrderToCashError, TenantScope
from outbox.postgres_store import PostgresOutboxStore
from provisioning.operation_request import is_tenant_id
from security.platform_context import (ContextRejected, ContextUnavailable, InvalidContext, TENANT_PROVISIONING, configured_validator, request_context_id)
from security.jwks import JwksSigningKeyResolver
from security.workload_auth import SigningKeyResolver, TokenValidationError, verify_workload_token


class PsycopgProbe:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def ping(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT 1")


class Config:
    def __init__(self) -> None:
        self.database_url = _require_env("DATABASE_URL")
        self.event_signing_secret = _require_env("BAOBAB_EVENT_SIGNING_SECRET")
        self.port = int(os.environ.get("HTTP_PORT", "8000"))
        self.workload_oidc_issuer = _require_env("BAOBAB_IAM_OIDC_ISSUER")
        self.workload_oidc_audience = os.environ.get("BAOBAB_IAM_OIDC_AUDIENCE", "baobab-erp")
        self.idempiere_credentials_by_ad_client = _load_idempiere_credentials()
        self.order_to_cash_process_ids = _load_order_to_cash_process_ids()
        self.provisioning = _load_provisioning_dependencies()
        self.context_validator = configured_validator(
            os.environ.get("ERP_CONTEXT_VALIDATION_URL"), os.environ.get("ERP_CONTEXT_VALIDATION_TOKEN_FILE"))


def _load_provisioning_dependencies() -> "ProvisioningDependencies | None":
    """Provisioning needs Control Plane's ERP assignment (a workload client under erp-assignment:read) and ERP's own deployment
    configuration (markets, native placements, environment). Unless ALL of it is set the operation answers 503 "not
    configured", never a guess: partial configuration is a deployment error and fails startup."""
    names = ("ERP_CONTROL_PLANE_URL", "ERP_CONTROL_PLANE_TOKEN_URL", "ERP_CONTROL_PLANE_CLIENT_ID",
             "ERP_CONTROL_PLANE_CLIENT_SECRET", "ERP_PROVISIONING_CONFIG_PATH")
    present = [name for name in names if os.environ.get(name)]
    if not present:
        return None
    if len(present) != len(names):
        raise RuntimeError("provisioning is partly configured; set all of " + ", ".join(names) + " or none")
    from provisioning.control_plane_client import ClientCredentialsTokenProvider, HttpControlPlaneAssignmentSource
    from provisioning.market_configuration import load_deployment_configuration

    deployment = load_deployment_configuration(os.environ["ERP_PROVISIONING_CONFIG_PATH"])
    tokens = ClientCredentialsTokenProvider(
        os.environ["ERP_CONTROL_PLANE_TOKEN_URL"], os.environ["ERP_CONTROL_PLANE_CLIENT_ID"],
        os.environ["ERP_CONTROL_PLANE_CLIENT_SECRET"], "erp-assignment:read")
    return ProvisioningDependencies(
        control_plane=HttpControlPlaneAssignmentSource(os.environ["ERP_CONTROL_PLANE_URL"], tokens),
        native_placement=deployment.native_placement, market_configuration=deployment.markets,
        target_environment=deployment.target_environment)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def _looks_like_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _load_idempiere_credentials() -> dict[int, IdempiereCredentials]:
    """Optional: {"<ad_client_id>": {"base_url": ..., "username": ..., "password": ...,
    "client_id": ..., "role_id": ..., "organization_id": ..., "warehouse_id": ...?}, ...}
    No credentials exist for any AD_Client in any environment this code has run in yet
    (no live iDempiere instance -- see this module's own docstring); an order-to-cash
    request against an AD_Client missing here gets UnconfiguredIdempiereClient, which
    raises IdempiereClientError on first use, surfaced as a clean 503."""
    raw = os.environ.get("IDEMPIERE_CLIENT_CREDENTIALS_JSON")
    if not raw:
        return {}
    parsed: dict[int, IdempiereCredentials] = {}
    for ad_client_id, fields in json.loads(raw).items():
        parsed[int(ad_client_id)] = IdempiereCredentials(
            base_url=fields["base_url"],
            username=fields["username"],
            password=fields["password"],
            client_id=int(fields["client_id"]),
            role_id=int(fields["role_id"]),
            organization_id=int(fields["organization_id"]),
            warehouse_id=int(fields["warehouse_id"]) if "warehouse_id" in fields else None,
        )
    return parsed


def _load_order_to_cash_process_ids() -> "order_to_cash.ProcessIds | None":
    """Optional, all-or-nothing: the five iDempiere native process IDs
    order_to_cash.service.ProcessIds needs (ADR-ERP-004 §26 -- document actions
    always go through a native process, never a direct DocStatus field patch).
    iDempiere assigns these per installation; None (not a guessed default) until
    every one of them is configured."""
    names = (
        "IDEMPIERE_PROCESS_COMPLETE_SALES_ORDER",
        "IDEMPIERE_PROCESS_COMPLETE_SHIPMENT",
        "IDEMPIERE_PROCESS_POST_CUSTOMER_INVOICE",
        "IDEMPIERE_PROCESS_COMPLETE_PAYMENT",
        "IDEMPIERE_PROCESS_ALLOCATE_PAYMENT",
    )
    values = {name: os.environ.get(name) for name in names}
    if not all(values.values()):
        return None
    return order_to_cash.ProcessIds(
        complete_sales_order=int(values["IDEMPIERE_PROCESS_COMPLETE_SALES_ORDER"]),
        complete_shipment=int(values["IDEMPIERE_PROCESS_COMPLETE_SHIPMENT"]),
        post_customer_invoice=int(values["IDEMPIERE_PROCESS_POST_CUSTOMER_INVOICE"]),
        complete_payment=int(values["IDEMPIERE_PROCESS_COMPLETE_PAYMENT"]),
        allocate_payment=int(values["IDEMPIERE_PROCESS_ALLOCATE_PAYMENT"]),
    )


# Endpoints a Baobab IAM workload token gates, and the scope each one requires
# (ADR-0014 §111, ADR-ERP-010 §41 "deny by default"). Kept as an explicit
# allowlist rather than "everything except health/events" so a new
# unauthenticated route is never accidentally exempt by omission. Every path
# here currently requires the same scope because only one is granted to any
# workload client today (baobab-iam/config/scopes/erp-integrate.json,
# baobab-erp-workload's only client) -- per-resource scopes (e.g. separating
# context resolution from mapping resolution, or order-to-cash from outbox) are
# tracked as a follow-on, not invented speculatively here.
_WORKLOAD_REQUIRED_SCOPES = {
    "/context/resolve": "erp:integrate",
    "/context/resolve-tenant": "erp:integrate",
    "/mapping/resolve": "erp:integrate",
    "/mapping/resolve-canonical": "erp:integrate",
    "/outbox/record": "erp:integrate",
    "/sales-orders": "erp:integrate",
    "/sales-orders/complete": "erp:integrate",
    "/shipments": "erp:integrate",
    "/shipments/complete": "erp:integrate",
    "/customer-invoices": "erp:integrate",
    "/customer-invoices/post": "erp:integrate",
    "/payments": "erp:integrate",
    "/payments/complete": "erp:integrate",
    "/payments/allocate": "erp:integrate",
}


def make_handler(config: Config, key_resolver: SigningKeyResolver | None = None) -> type[BaseHTTPRequestHandler]:
    resolver = key_resolver or JwksSigningKeyResolver(
        f"{config.workload_oidc_issuer}/protocol/openid-connect/certs"
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            pass  # structured logging is deployment configuration, not hard-coded here

        def _send_json(self, status: int, body: dict, *, content_type: str = "application/json",
                       correlation_id: str | None = None, headers: dict | None = None) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if correlation_id:
                self.send_header("X-Correlation-ID", correlation_id)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def _request_correlation_id(self) -> str:
            """The caller's X-Correlation-ID when it is a valid UUID, otherwise a fresh one. Legacy
            routes never reject a bad header (only the contract-defined boundary does); they
            just do not echo it."""
            if not hasattr(self, "_correlation"):
                self._correlation = correlation_id_from(self.headers.get("X-Correlation-ID")) or str(uuid.uuid4())
            return self._correlation

        def _error(self, status: int, detail: str | None = None) -> None:
            """Every error response is RFC 9457 application/problem+json (contracts/errors/v1).
            Legacy callers get flat documents (scalar members only): the iDempiere-side client
            parses flat JSON. `detail` is a safe, short description; internals are never echoed
            for 401/500."""
            correlation_id = self._request_correlation_id()
            _, trace_id = trace_id_from(self.headers.get("traceparent"))
            _, body = problem(kind_for_status(status), correlation_id=correlation_id, trace_id=trace_id,
                              detail=detail)
            self._send_json(status, body, content_type="application/problem+json", correlation_id=correlation_id)

        def _serve_boundary(self, method: str, split) -> bool:
            """contracts/erp/v1/openapi.yaml surface (served with or without the /v1 base path).
            Returns False when the path is not a boundary route so legacy routing continues.
            Every response, including errors, is contract-shaped: JSON, or RFC 9457
            application/problem+json with the correlation id echoed."""
            path = split.path[3:] if split.path.startswith("/v1/") else split.path
            route = boundary.match(method, path)
            if route is None:
                return False
            supplied = correlation_id_from(self.headers.get("X-Correlation-ID"))
            correlation_id = supplied or str(uuid.uuid4())
            traceparent_ok, trace_id = trace_id_from(self.headers.get("traceparent"))

            def fail(kind: str, detail: str | None = None, code: str | None = None,
                     headers: dict | None = None) -> bool:
                status, body = problem(kind, correlation_id=correlation_id, trace_id=trace_id, detail=detail, code=code)
                self._send_json(status, body, content_type="application/problem+json", correlation_id=correlation_id,
                                headers=headers)
                return True

            try:
                identity = verify_workload_token(
                    self.headers.get("Authorization"),
                    issuer=config.workload_oidc_issuer,
                    audience=config.workload_oidc_audience,
                    key_resolver=resolver,
                )
            except TokenValidationError:
                return fail("unauthenticated")
            if supplied is None or not traceparent_ok:
                return fail("invalid_request", "X-Correlation-ID must be a UUID and traceparent a W3C trace context")
            if not identity.has_role(route.scope):
                return fail("forbidden")
            tenant_scoped = route.handler is not boundary.not_implemented
            if tenant_scoped and not route.context_required and identity.tenant_id is None:
                return fail("tenant_context_required", "the token carries no resolved tenant")
            raw_body = b""
            if method == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return fail("invalid_request", "Content-Length is not a number")
                if length > MAX_BODY_BYTES:
                    return fail("invalid_request", "the request body is too large")
                raw_body = self.rfile.read(length) if length > 0 else b""
            tenant_id = identity.tenant_id
            context_authority = None
            if route.context_required:
                try:
                    context_id = request_context_id(method, raw_body, split.query)
                except InvalidContext:
                    return fail("invalid_request", "context_id must be a single UUID")
                # Every 503 of the contract carries an integer Retry-After (ERP API ServiceUnavailable).
                retry_later = {"Retry-After": CONTEXT_RETRY_AFTER_SECONDS}
                validator = getattr(config, "context_validator", None)
                if validator is None:
                    return fail("unavailable", headers=retry_later)
                try:
                    validated = validator.validate(
                        context_id=context_id,
                        subject_token=self.headers["Authorization"].split()[1],
                        correlation_id=correlation_id)
                except ContextRejected:
                    return fail("forbidden", code="ERP_CONTEXT_REJECTED")
                except ContextUnavailable:
                    return fail("unavailable", headers=retry_later)
                tenant_id = validated.tenant_id
                if identity.tenant_id is not None and identity.tenant_id != tenant_id:
                    return fail("forbidden", code="ERP_CONTEXT_REJECTED")
                # A context is authority only for what the Control Plane says it is authority FOR (Shared erp/v1 1.2.0).
                # Provisioning accepts only a TENANT_PROVISIONING context and every business-data read only a RUNTIME one;
                # a context of the other purpose is the same indistinguishable rejection as any other.
                if validated.purpose != route.context_purpose:
                    return fail("forbidden", code="ERP_CONTEXT_REJECTED")
                context_authority = validated.provisioning_authority
                if method == "POST":
                    requested_tenant = json.loads(raw_body).get("tenant_id")
                    # A malformed tenant is an invalid document (400), not an authority disagreement: only a different
                    # well-formed tenant is refused as ERP_CONTEXT_REJECTED.
                    if not is_tenant_id(requested_tenant):
                        return fail("invalid_request", "tenant_id must be a valid tenant identifier")
                    if requested_tenant != tenant_id:
                        return fail("forbidden", code="ERP_CONTEXT_REJECTED")
                    # Context authority and plan authority are independent and both must hold: the plan the request names
                    # must be exactly the plan the context is bound to. (A request whose plan tuple is missing or malformed
                    # is an invalid document and is answered 400 by the request parser; nothing is provisioned either way.)
                    named = json.loads(raw_body).get("control_plane_authority")
                    if route.context_purpose == TENANT_PROVISIONING and isinstance(named, dict) \
                            and named.keys() == {"tenant_provisioning_id", "plan_id", "plan_version", "plan_digest"} \
                            and (context_authority is None or named != {
                                "tenant_provisioning_id": context_authority.tenant_provisioning_id,
                                "plan_id": context_authority.plan_id, "plan_version": context_authority.plan_version,
                                "plan_digest": context_authority.plan_digest}):
                        return fail("forbidden", code="ERP_CONTEXT_REJECTED")
            with psycopg.connect(config.database_url) as connection:
                result = route.handler(
                    tenant_id=tenant_id,
                    store=PostgresCanonicalMappingStore(connection),
                    argument=route.argument,
                    query_string=split.query,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    connection=connection,
                    body=raw_body,
                    idempotency_key=self.headers.get("Idempotency-Key"),
                    principal=identity.principal,
                    context_authority=context_authority,
                    provisioning=config.provisioning,
                    idempiere_for=self._build_idempiere_client,
                )
            status, body, *rest = result
            content_type = "application/problem+json" if status >= 400 else "application/json"
            self._send_json(status, body, content_type=content_type, correlation_id=correlation_id,
                            headers=rest[0] if rest else None)
            return True

        def _authorize_workload(self, required_scope: str) -> bool:
            """Returns True and lets the caller proceed, or sends a 401/403 itself
            and returns False. 401 means nothing about the caller could be trusted
            (missing/invalid/expired/wrong-audience token); 403 means the caller
            authenticated as a real Baobab IAM workload but its token doesn't grant
            required_scope -- these are kept distinct so a legitimate workload with
            the wrong scope gets an actionable signal, while an untrusted caller
            never learns whether a scope check even ran."""
            try:
                identity = verify_workload_token(
                    self.headers.get("Authorization"),
                    issuer=config.workload_oidc_issuer,
                    audience=config.workload_oidc_audience,
                    key_resolver=resolver,
                )
            except TokenValidationError as exc:
                self._error(401)
                return False
            if not identity.has_role(required_scope):
                self._error(403, "workload token does not grant the required scope")
                return False
            return True

        def _guarded(self, handler) -> None:
            """An unexpected exception becomes a 500 problem document (no internals echoed, details go
            to the log) rather than the stdlib's HTML error page."""
            try:
                handler()
            except (BrokenPipeError, ConnectionResetError):
                raise
            except Exception:  # noqa: BLE001 - last-resort boundary
                logging.getLogger("baobab.erp").exception("unhandled error serving %s %s", self.command, self.path)
                self._error(500)

        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            self._guarded(self._do_get)

        def _do_get(self) -> None:
            split = urlsplit(self.path)
            query = parse_qs(split.query)

            if split.path == "/health/live":
                self._send_json(200, liveness())
                return
            if split.path == "/health/ready":
                try:
                    with psycopg.connect(config.database_url) as connection:
                        self._send_json(200, readiness(PsycopgProbe(connection)))
                except Exception as exc:  # noqa: BLE001 - reported as a 503, not raised
                    self._error(503, "the database is not reachable")
                return
            if self._serve_boundary("GET", split):
                return
            required_scope = _WORKLOAD_REQUIRED_SCOPES.get(split.path)
            if required_scope is not None and not self._authorize_workload(required_scope):
                return
            if split.path == "/context/resolve":
                self._handle_context_resolve(query)
                return
            if split.path == "/context/resolve-tenant":
                self._handle_context_resolve_tenant(query)
                return
            if split.path == "/mapping/resolve":
                self._handle_mapping_resolve(query)
                return
            if split.path == "/mapping/resolve-canonical":
                self._handle_mapping_resolve_canonical(query)
                return
            self._error(404, "not found")

        def _query_param(self, query: dict, name: str) -> str | None:
            values = query.get(name)
            return values[0] if values else None

        def _handle_context_resolve(self, query: dict) -> None:
            tenant_id = self._query_param(query, "tenant_id")
            entity_id = self._query_param(query, "entity_id")
            if not tenant_id or not entity_id:
                self._error(400, "tenant_id and entity_id are both required")
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    store = PostgresTenantMappingStore(connection)
                    context = resolve_context(tenant_id, entity_id, store)
            except ContextResolutionError as exc:
                self._error(404, str(exc))
                return
            self._send_json(200, {"ad_client_id": context.ad_client_id, "ad_org_id": context.ad_org_id})

        def _handle_context_resolve_tenant(self, query: dict) -> None:
            ad_client_id = self._query_param(query, "ad_client_id")
            ad_org_id = self._query_param(query, "ad_org_id")
            if not ad_client_id or not ad_client_id.isdigit() or not ad_org_id or not ad_org_id.isdigit():
                self._error(400, "numeric ad_client_id and ad_org_id are both required")
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    store = PostgresTenantMappingStore(connection)
                    context = resolve_tenant(int(ad_client_id), int(ad_org_id), store)
            except ContextResolutionError as exc:
                self._error(404, str(exc))
                return
            self._send_json(200, {"tenant_id": context.tenant_id, "entity_id": context.entity_id})

        def _handle_mapping_resolve(self, query: dict) -> None:
            tenant_id = self._query_param(query, "tenant_id")
            canonical_type = self._query_param(query, "canonical_type")
            canonical_id = self._query_param(query, "canonical_id")
            if not tenant_id or not canonical_type or not canonical_id:
                self._error(400, "tenant_id, canonical_type and canonical_id are all required")
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    store = PostgresCanonicalMappingStore(connection)
                    ref = resolve_to_native(tenant_id, canonical_type, canonical_id, store)
            except MappingNotFoundError as exc:
                self._error(404, str(exc))
                return
            self._send_json(200, {"table": ref.table, "record_id": ref.record_id})

        def _handle_mapping_resolve_canonical(self, query: dict) -> None:
            tenant_id = self._query_param(query, "tenant_id")
            table = self._query_param(query, "table")
            record_id = self._query_param(query, "record_id")
            if not tenant_id or not table or not record_id or not record_id.isdigit():
                self._error(400, "tenant_id, table and a numeric record_id are all required")
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    store = PostgresCanonicalMappingStore(connection)
                    canonical_id = resolve_to_canonical(tenant_id, table, int(record_id), store)
            except MappingNotFoundError as exc:
                self._error(404, str(exc))
                return
            self._send_json(200, {"canonical_id": canonical_id})

        def do_POST(self) -> None:  # noqa: N802 - stdlib method name
            self._guarded(self._do_post)

        def _do_post(self) -> None:
            if self._serve_boundary("POST", urlsplit(self.path)):
                return
            if self.path == "/events/inbound":
                self._handle_inbound_event()
                return
            required_scope = _WORKLOAD_REQUIRED_SCOPES.get(self.path)
            if required_scope is not None:
                if not self._authorize_workload(required_scope):
                    return
                body = self._read_json_body()
                if body is None:
                    return
                self._route_post(self.path, body)
                return
            self._error(404, "not found")

        def _handle_inbound_event(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            signature = self.headers.get("X-Baobab-Signature", "")
            try:
                with psycopg.connect(config.database_url) as connection:
                    store = PostgresInboxStore(connection)
                    event = receive(body, signature, config.event_signing_secret, store)
            except InvalidSignatureError:
                self._error(401, "invalid signature")
                return
            except ValueError as exc:
                self._error(400, str(exc))
                return
            self._send_json(200, {"status": "accepted", "event_id": event.id})

        def _read_json_body(self) -> dict | None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            if not raw:
                self._error(400, "a JSON request body is required")
                return None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._error(400, f"invalid JSON body: {exc}")
                return None
            if not isinstance(parsed, dict):
                self._error(400, "request body must be a JSON object")
                return None
            return parsed

        def _route_post(self, path: str, body: dict) -> None:
            handlers = {
                "/outbox/record": self._handle_outbox_record,
                "/sales-orders": self._handle_create_sales_order,
                "/sales-orders/complete": self._handle_complete_sales_order,
                "/shipments": self._handle_create_shipment,
                "/shipments/complete": self._handle_complete_shipment,
                "/customer-invoices": self._handle_create_customer_invoice,
                "/customer-invoices/post": self._handle_post_customer_invoice,
                "/payments": self._handle_create_payment,
                "/payments/complete": self._handle_complete_payment,
                "/payments/allocate": self._handle_allocate_payment,
            }
            handlers[path](body)

        def _handle_outbox_record(self, body: dict) -> None:
            """Called by the OSGi outbox bundle (BaobabOutboxPublisher) -- the caller has
            already resolved tenant/legal-entity identity itself (see that bundle's own
            Javadoc), so this endpoint does no context resolution of its own, unlike the
            order-to-cash endpoints below."""
            required = ("event_type", "tenant_id", "entity_id", "correlation_id", "payload")
            missing = [name for name in required if name not in body]
            if missing:
                self._error(400, f"missing required fields: {', '.join(missing)}")
                return
            if not isinstance(body["payload"], dict):
                self._error(400, "payload must be a JSON object")
                return
            envelope = EventEnvelope(
                event_id=str(uuid.uuid4()),
                event_type=body["event_type"],
                schema_version="1.0",
                occurred_at=datetime.now(timezone.utc),
                source="baobab-erp",
                correlation_id=body["correlation_id"],
                tenant_id=body["tenant_id"],
                entity_id=body["entity_id"],
                payload=body["payload"],
            )
            with psycopg.connect(config.database_url) as connection:
                store = PostgresOutboxStore(connection)
                store.record(envelope)
            self._send_json(202, {"status": "accepted", "delivery": "held", "event_id": envelope.event_id})

        def _resolve_tenant_scope(self, connection, body: dict) -> TenantScope | None:
            tenant_id = body.get("tenant_id")
            entity_id = body.get("entity_id")
            if not tenant_id or not entity_id:
                self._error(400, "tenant_id and entity_id are both required")
                return None
            try:
                store = PostgresTenantMappingStore(connection)
                context = resolve_context(tenant_id, entity_id, store)
            except ContextResolutionError as exc:
                self._error(404, str(exc))
                return None
            return TenantScope(
                tenant_id=tenant_id, legal_entity_id=entity_id,
                ad_client_id=context.ad_client_id, ad_org_id=context.ad_org_id,
            )

        def _validate_uuid_fields(self, body: dict, *field_names: str) -> bool:
            """Every caller-supplied canonical id order_to_cash passes to
            mapping.postgres_store ends up bound to an entity_mapping.canonical_id
            column, which is a native Postgres UUID (db/migrations/0003) -- a
            malformed value reaching that far raises a raw psycopg.DataError with
            no handler for it anywhere in this call chain. Validating shape here,
            matching this file's own established convention
            (_handle_context_resolve_tenant's ad_client_id.isdigit() check), turns
            that into a clean 400 instead of a crashed connection."""
            malformed = [name for name in field_names if name in body and not _looks_like_uuid(body[name])]
            if malformed:
                self._error(400, f"not a valid UUID: {', '.join(malformed)}")
                return False
            return True

        def _build_idempiere_client(self, ad_client_id: int):
            credentials = config.idempiere_credentials_by_ad_client.get(ad_client_id)
            if credentials is None:
                return UnconfiguredIdempiereClient(IdempiereEndpoint(base_url="(unconfigured)", ad_client_id=ad_client_id, ad_org_id=0))
            return RestIdempiereClient(credentials)

        def _process_ids_or_503(self):
            if config.order_to_cash_process_ids is None:
                self._error(503, "order-to-cash native process IDs are not configured for this deployment")
                return None
            return config.order_to_cash_process_ids

        def _handle_create_sales_order(self, body: dict) -> None:
            required = ("commerce_order_canonical_id", "business_partner_native_id", "document_currency", "lines")
            missing = [name for name in required if name not in body]
            if missing:
                self._error(400, f"missing required fields: {', '.join(missing)}")
                return
            if not self._validate_uuid_fields(body, "commerce_order_canonical_id"):
                return
            order_version = body.get("order_version")
            if order_version is not None and (isinstance(order_version, bool) or not isinstance(order_version, int)
                                             or order_version < 1):
                self._error(400, "order_version must be a positive integer")
                return
            try:
                lines = tuple(
                    OrderLine(
                        product_canonical_id=line["product_canonical_id"],
                        quantity=str(line["quantity"]),
                        unit_price=str(line["unit_price"]),
                    )
                    for line in body["lines"]
                )
            except (KeyError, TypeError):
                self._error(400, "each line requires product_canonical_id, quantity, unit_price")
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    scope = self._resolve_tenant_scope(connection, body)
                    if scope is None:
                        return
                    idempiere = self._build_idempiere_client(scope.ad_client_id)
                    mappings = PostgresCanonicalMappingStore(connection)
                    ref = order_to_cash.create_sales_order(
                        scope=scope,
                        commerce_order_canonical_id=body["commerce_order_canonical_id"],
                        business_partner_native_id=int(body["business_partner_native_id"]),
                        document_currency=body["document_currency"],
                        lines=lines,
                        idempiere=idempiere,
                        mappings=mappings,
                        order_version=order_version,
                        consequences=PostgresOrderConsequenceStore(connection),
                        outbox=PostgresOutboxStore(connection),
                        correlation_id=body.get("correlation_id"),
                    )
            except OrderToCashError as exc:
                self._error(400, str(exc))
                return
            except IdempiereClientError as exc:
                self._error(502, f"iDempiere rejected the request: {exc}")
                return
            self._send_json(201, {"canonical_id": ref.canonical_id, "table": ref.table, "native_id": ref.native_id})

        def _handle_complete_sales_order(self, body: dict) -> None:
            self._handle_complete_document(
                body, required_id_field="commerce_order_canonical_id",
                run=lambda scope, idempiere, mappings, outbox, process_ids, correlation_id, consequences, outcomes: order_to_cash.complete_sales_order(
                    scope=scope, commerce_order_canonical_id=body["commerce_order_canonical_id"],
                    correlation_id=correlation_id, process_ids=process_ids,
                    idempiere=idempiere, mappings=mappings, outbox=outbox, consequences=consequences,
                ),
            )

        def _handle_create_shipment(self, body: dict) -> None:
            required = ("shipment_canonical_id", "commerce_order_canonical_id")
            missing = [name for name in required if name not in body]
            if missing:
                self._error(400, f"missing required fields: {', '.join(missing)}")
                return
            if not self._validate_uuid_fields(body, "shipment_canonical_id", "commerce_order_canonical_id"):
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    scope = self._resolve_tenant_scope(connection, body)
                    if scope is None:
                        return
                    idempiere = self._build_idempiere_client(scope.ad_client_id)
                    mappings = PostgresCanonicalMappingStore(connection)
                    ref = order_to_cash.create_shipment(
                        scope=scope, shipment_canonical_id=body["shipment_canonical_id"],
                        commerce_order_canonical_id=body["commerce_order_canonical_id"],
                        idempiere=idempiere, mappings=mappings,
                        consequences=PostgresOrderConsequenceStore(connection),
                    )
            except MappingNotFoundError as exc:
                self._error(404, str(exc))
                return
            except OrderToCashError as exc:
                self._error(400, str(exc))
                return
            except IdempiereClientError as exc:
                self._error(502, f"iDempiere rejected the request: {exc}")
                return
            self._send_json(201, {"canonical_id": ref.canonical_id, "table": ref.table, "native_id": ref.native_id})

        def _handle_complete_shipment(self, body: dict) -> None:
            self._handle_complete_document(
                body, required_id_field="shipment_canonical_id",
                run=lambda scope, idempiere, mappings, outbox, process_ids, correlation_id, consequences, outcomes: order_to_cash.complete_shipment(
                    scope=scope, shipment_canonical_id=body["shipment_canonical_id"],
                    correlation_id=correlation_id, process_ids=process_ids,
                    idempiere=idempiere, mappings=mappings, outbox=outbox, consequences=consequences,
                ),
            )

        def _handle_create_customer_invoice(self, body: dict) -> None:
            if "commerce_order_canonical_id" not in body:
                self._error(400, "missing required field: commerce_order_canonical_id")
                return
            if not self._validate_uuid_fields(body, "commerce_order_canonical_id"):
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    scope = self._resolve_tenant_scope(connection, body)
                    if scope is None:
                        return
                    idempiere = self._build_idempiere_client(scope.ad_client_id)
                    mappings = PostgresCanonicalMappingStore(connection)
                    ref = order_to_cash.create_customer_invoice(
                        scope=scope, commerce_order_canonical_id=body["commerce_order_canonical_id"],
                        idempiere=idempiere, mappings=mappings,
                        consequences=PostgresOrderConsequenceStore(connection),
                    )
            except MappingNotFoundError as exc:
                self._error(404, str(exc))
                return
            except OrderToCashError as exc:
                self._error(400, str(exc))
                return
            except IdempiereClientError as exc:
                self._error(502, f"iDempiere rejected the request: {exc}")
                return
            self._send_json(201, {"canonical_id": ref.canonical_id, "table": ref.table, "native_id": ref.native_id})

        def _handle_post_customer_invoice(self, body: dict) -> None:
            self._handle_complete_document(
                body, required_id_field="invoice_canonical_id",
                run=lambda scope, idempiere, mappings, outbox, process_ids, correlation_id, consequences, outcomes: order_to_cash.post_customer_invoice(
                    scope=scope, invoice_canonical_id=body["invoice_canonical_id"],
                    correlation_id=correlation_id, process_ids=process_ids,
                    idempiere=idempiere, mappings=mappings, outbox=outbox, consequences=consequences, outcomes=outcomes,
                ),
            )

        def _handle_create_payment(self, body: dict) -> None:
            required = ("payment_canonical_id", "business_partner_native_id", "amount", "currency")
            missing = [name for name in required if name not in body]
            if missing:
                self._error(400, f"missing required fields: {', '.join(missing)}")
                return
            if not self._validate_uuid_fields(body, "payment_canonical_id"):
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    scope = self._resolve_tenant_scope(connection, body)
                    if scope is None:
                        return
                    idempiere = self._build_idempiere_client(scope.ad_client_id)
                    mappings = PostgresCanonicalMappingStore(connection)
                    ref = order_to_cash.create_payment(
                        scope=scope, payment_canonical_id=body["payment_canonical_id"],
                        business_partner_native_id=int(body["business_partner_native_id"]),
                        amount=str(body["amount"]), currency=body["currency"],
                        idempiere=idempiere, mappings=mappings,
                    )
            except OrderToCashError as exc:
                self._error(400, str(exc))
                return
            except IdempiereClientError as exc:
                self._error(502, f"iDempiere rejected the request: {exc}")
                return
            self._send_json(201, {"canonical_id": ref.canonical_id, "table": ref.table, "native_id": ref.native_id})

        def _handle_complete_payment(self, body: dict) -> None:
            self._handle_complete_document(
                body, required_id_field="payment_canonical_id",
                run=lambda scope, idempiere, mappings, outbox, process_ids, correlation_id, consequences, outcomes: order_to_cash.complete_payment(
                    scope=scope, payment_canonical_id=body["payment_canonical_id"],
                    correlation_id=correlation_id, process_ids=process_ids,
                    idempiere=idempiere, mappings=mappings, outbox=outbox, outcomes=outcomes,
                ),
            )

        def _handle_allocate_payment(self, body: dict) -> None:
            required = ("payment_canonical_id", "invoice_canonical_id", "amount")
            missing = [name for name in required if name not in body]
            if missing:
                self._error(400, f"missing required fields: {', '.join(missing)}")
                return
            if not self._validate_uuid_fields(body, "payment_canonical_id", "invoice_canonical_id"):
                return
            process_ids = self._process_ids_or_503()
            if process_ids is None:
                return
            try:
                with psycopg.connect(config.database_url) as connection:
                    scope = self._resolve_tenant_scope(connection, body)
                    if scope is None:
                        return
                    idempiere = self._build_idempiere_client(scope.ad_client_id)
                    mappings = PostgresCanonicalMappingStore(connection)
                    outbox = PostgresOutboxStore(connection)
                    order_to_cash.allocate_payment(
                        scope=scope, payment_canonical_id=body["payment_canonical_id"],
                        invoice_canonical_id=body["invoice_canonical_id"], amount=str(body["amount"]),
                        correlation_id=body.get("correlation_id", ""), process_ids=process_ids,
                        idempiere=idempiere, mappings=mappings, outbox=outbox,
                        consequences=PostgresOrderConsequenceStore(connection),
                        outcomes=PostgresDocumentOutcomeStore(connection),
                    )
            except MappingNotFoundError as exc:
                self._error(404, str(exc))
                return
            except OrderToCashError as exc:
                self._error(400, str(exc))
                return
            except IdempiereClientError as exc:
                self._error(502, f"iDempiere rejected the request: {exc}")
                return
            self._send_json(200, {"status": "allocated"})

        def _handle_complete_document(self, body: dict, *, required_id_field: str, run) -> None:
            """Shared shape for every *_complete/_post endpoint: resolve scope, get
            process_ids (or 503), run the given order_to_cash call inside one
            connection/transaction, translate its exceptions the same way every time."""
            if required_id_field not in body:
                self._error(400, f"missing required field: {required_id_field}")
                return
            if not self._validate_uuid_fields(body, required_id_field):
                return
            process_ids = self._process_ids_or_503()
            if process_ids is None:
                return
            correlation_id = body.get("correlation_id", "")
            try:
                with psycopg.connect(config.database_url) as connection:
                    scope = self._resolve_tenant_scope(connection, body)
                    if scope is None:
                        return
                    idempiere = self._build_idempiere_client(scope.ad_client_id)
                    mappings = PostgresCanonicalMappingStore(connection)
                    outbox = PostgresOutboxStore(connection)
                    run(scope, idempiere, mappings, outbox, process_ids, correlation_id, PostgresOrderConsequenceStore(connection),
                        PostgresDocumentOutcomeStore(connection))
            except MappingNotFoundError as exc:
                self._error(404, str(exc))
                return
            except OrderToCashError as exc:
                self._error(400, str(exc))
                return
            except IdempiereClientError as exc:
                self._error(502, f"iDempiere rejected the request: {exc}")
                return
            self._send_json(200, {"status": "completed"})

    return Handler


def main() -> None:
    config = Config()
    server = ThreadingHTTPServer(("0.0.0.0", config.port), make_handler(config))  # noqa: S104 - container-internal bind
    server.serve_forever()


if __name__ == "__main__":
    main()
