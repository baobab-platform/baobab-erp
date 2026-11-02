"""DEV-11 explicit, operator-owned authority composition for one Trade order.

A signed CloudEvent is DATA, never a CP mandate. This registry is a separate
read-only deployment input prepared *after* independently observing the exact
CP-minted RUNTIME context. A missing/mismatched entry blocks native execution.
The authority adapter performs live OAuth2 -> CP legal-actor and documentary
checks EACH claim; the native provider checks installed ERP placement, finance
baseline, and actual iDempiere AD_Client/AD_Org through its real REST adapter.

This module does not mint contexts, create mandates, accept applicant grants,
or declare the external iDempiere JVM ModelValidator certified. Independent
JVM and final business-effect observation remain L4 acceptance requirements.
"""
from __future__ import annotations

import json
import os
import re
import stat
import uuid
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psycopg

from inbox.postgres_queue import Claim
from integration.idempiere_client import IdempiereClientError
from order_to_cash.documentary_restriction import HttpControlPlaneDocumentaryRestrictionAssessor
from order_to_cash.inbox_execution import InboxNativeAuthority
from order_to_cash.legal_actor_gate import LegalActorNotAuthorised, LegalActorOperation
from order_to_cash.legal_actor_http_client import HttpControlPlaneLegalActorAssessor
from order_to_cash.native_action_gate import NativeActionPolicy
from provisioning.control_plane_client import ClientCredentialsTokenProvider
from shared_contracts.http import RejectRedirect

_EXPECTED_SOURCE = "urn:baobab-platform:service:baobab-trade"
_TYPE = "com.baobab-platform.trade.order.placed.v1"
_CAPABILITY = re.compile(r"^[a-z][a-z0-9._-]{2,199}$")
_ACTIVITY = re.compile(r"^[A-Z][A-Z0-9_]{2,100}$")
_AUTH_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{2,255}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_LEGAL = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_ALLOWED = frozenset({
    "event_id", "source", "tenant_id", "idempotency_key",
    "commerce_order_id", "legal_entity_id", "context_id",
    "operating_organisation_id", "market", "activity", "capability",
    "authority_reference", "engine_instance_id",
    "ad_client_id", "ad_org_id", "finance_baseline_version",
})
_MAX_REGISTRY_BYTES = 256 * 1024


def _duplicate_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("DEV11_REGISTRY_DUPLICATE_PROPERTY")
        data[key] = value
    return data


def _secure_text(path: str, *, limit=_MAX_REGISTRY_BYTES) -> str:
    """Refuse symlinks/group-write and overly large operator input."""
    if not path or not os.path.isabs(path):
        raise ValueError("DEV11_OPERATOR_FILE_REQUIRED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > limit:
            raise ValueError("DEV11_OPERATOR_FILE_NOT_IMMUTABLE")
        with os.fdopen(os.dup(fd), encoding="utf-8") as stream:
            return stream.read(limit + 1)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class AuthorityEntry:
    event_id: str
    source: str
    tenant_id: str
    idempotency_key: str
    commerce_order_id: str
    legal_entity_id: str
    context_id: str
    operating_organisation_id: str
    market: str
    activity: str
    capability: str
    authority_reference: str
    engine_instance_id: str
    ad_client_id: int
    ad_org_id: int
    finance_baseline_version: int

    @classmethod
    def parse(cls, raw: object):
        if not isinstance(raw, dict) or set(raw) != _ALLOWED:
            raise ValueError("DEV11_REGISTRY_ENTRY_FIELDS_INVALID")
        for name in ("event_id", "context_id", "operating_organisation_id"):
            try:
                if str(uuid.UUID(raw[name])) != raw[name]:
                    raise ValueError()
            except (TypeError, ValueError, AttributeError):
                raise ValueError("DEV11_REGISTRY_UUID_INVALID") from None
        if (raw["source"] != _EXPECTED_SOURCE
                or not isinstance(raw["tenant_id"], str)
                or not re.fullmatch(r"tn_[a-z0-9]{3,60}", raw["tenant_id"])
                or not all(isinstance(raw[key], str) and _REF.fullmatch(raw[key])
                           for key in ("idempotency_key", "commerce_order_id"))
                or not isinstance(raw["legal_entity_id"], str)
                or not _LEGAL.fullmatch(raw["legal_entity_id"])
                or (raw["market"] not in {"UG", "ZA"} and not (
                    raw["market"] == "US"
                    and os.environ.get("BAOBAB_ENVIRONMENT") == "integration"
                    and os.environ.get("BAOBAB_DEV11_REAL_JVM_GATE_ENABLED") == "true"
                    and os.environ.get("BAOBAB_DEV11_GARDENWORLD_US_FIXTURE") == "true"))
                or not isinstance(raw["activity"], str) or not _ACTIVITY.fullmatch(raw["activity"])
                or not isinstance(raw["capability"], str) or not _CAPABILITY.fullmatch(raw["capability"])
                or not isinstance(raw["authority_reference"], str)
                or not _AUTH_REFERENCE.fullmatch(raw["authority_reference"])
                or not isinstance(raw["engine_instance_id"], str)
                or not re.fullmatch(r"ei_[a-z0-9]{3,60}", raw["engine_instance_id"])
                or any(type(raw[field]) is not int or raw[field] < 1
                       for field in ("ad_client_id", "ad_org_id", "finance_baseline_version"))):
            raise ValueError("DEV11_REGISTRY_SCOPE_INVALID")
        return cls(**raw)

    def matches(self, claim: Claim) -> bool:
        data = claim.data
        return (claim.event_type == _TYPE
                and claim.source == self.source
                and claim.event_id == self.event_id
                and claim.tenant_id == self.tenant_id
                and claim.idempotency_key == self.idempotency_key
                and isinstance(data, dict)
                and data.get("commerce_order_id") == self.commerce_order_id
                and data.get("legal_entity_id") == self.legal_entity_id)


class OperatorAuthorityRegistry:
    """One exact immutable mapping per event; never supplied by broker input."""

    def __init__(self, path: str):
        raw = json.loads(_secure_text(path), object_pairs_hook=_duplicate_keys)
        if (not isinstance(raw, dict) or set(raw) != {"schema", "entries"}
                or raw["schema"] != "baobab.erp.dev11.operator-authority.v1"
                or not isinstance(raw["entries"], list)
                or not 1 <= len(raw["entries"]) <= 100):
            raise ValueError("DEV11_OPERATOR_REGISTRY_INVALID")
        entries = [AuthorityEntry.parse(entry) for entry in raw["entries"]]
        if len({entry.event_id for entry in entries}) != len(entries):
            raise ValueError("DEV11_DUPLICATE_EVENT_AUTHORITY")
        self.entries = {entry.event_id: entry for entry in entries}

    def for_claim(self, claim: Claim) -> AuthorityEntry | None:
        entry = self.entries.get(claim.event_id)
        return entry if entry is not None and entry.matches(claim) else None


def _native_id(value: object):
    if isinstance(value, dict):
        value = value.get("id")
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise LegalActorNotAuthorised("native ERP organisation identity unreadable")


class NativeOrderProviderReadiness:
    """Independent real placement, baseline and iDempiere org checks.

    Not a replacement for the installed iDempiere native JVM PEP. L4 verifier
    additionally checks the JVM sentinel and resulting native C_Order row.
    """

    def __init__(self, connection: psycopg.Connection,
                 engine_for: Callable, entry: AuthorityEntry):
        self.db, self.engine_for, self.entry = connection, engine_for, entry

    def ensure_legal_actor_usable(self, operation: LegalActorOperation, mandate_id: str) -> None:
        e = self.entry
        if (not mandate_id or not operation.context_id == e.context_id or
                operation.tenant_id != e.tenant_id or
                operation.expected_legal_entity_id != e.legal_entity_id or
                operation.operating_organisation_id != e.operating_organisation_id or
                operation.market != e.market or
                operation.operation_reference != e.commerce_order_id):
            raise LegalActorNotAuthorised("native ERP provider authority scope mismatch")

        # Trusted per-organisation placement, never a tenant DEFAULT or market
        # inferred from seller locale. Require exactly one CURRENT matching row.
        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """SELECT count(*) FROM baobab_native.native_placement
                       WHERE tenant_id=%s AND engine_instance_id=%s
                         AND operating_organisation_id=%s::uuid
                         AND legal_entity_id=%s AND market=%s
                         AND ad_client_id=%s AND ad_org_id=%s
                         AND effective_from <= now()
                         AND (effective_to IS NULL OR effective_to > now())""",
                    (e.tenant_id, e.engine_instance_id, e.operating_organisation_id,
                     e.legal_entity_id, e.market, e.ad_client_id, e.ad_org_id))
                placement = cur.fetchone()[0]
                cur.execute(
                    """SELECT count(*) FROM baobab.tenant_mapping
                       WHERE tenant_id=%s AND entity_id=%s AND
                             engine_instance_id=%s AND ad_client_id=%s
                         AND ad_org_id=%s AND status='active'""",
                    (e.tenant_id, e.legal_entity_id, e.engine_instance_id,
                     e.ad_client_id, e.ad_org_id))
                target = cur.fetchone()[0]
                cur.execute(
                    """SELECT count(*) FROM baobab.financial_configuration_baseline b
                       WHERE b.legal_entity_id=%s AND b.version=%s
                         AND b.effective_from <= current_date
                         AND NOT EXISTS (
                           SELECT 1 FROM baobab.financial_configuration_baseline_withdrawal w
                            WHERE w.legal_entity_id=b.legal_entity_id AND w.version=b.version)
                         AND NOT EXISTS (
                           SELECT 1 FROM baobab.financial_configuration_baseline newer
                            WHERE newer.legal_entity_id=b.legal_entity_id
                              AND newer.effective_from <= current_date
                              AND (newer.effective_from, newer.version)
                                  > (b.effective_from, b.version))""",
                    (e.legal_entity_id, e.finance_baseline_version))
                baseline = cur.fetchone()[0]
        except psycopg.Error:
            # Missing native migration, unavailable PG or withdrawn finance
            # evidence must never become optimistic native permission.
            self.db.rollback()
            raise LegalActorNotAuthorised(
                "ERP native placement or Finance baseline unavailable"
            ) from None
        if (placement, target, baseline) != (1, 1, 1):
            raise LegalActorNotAuthorised("ERP placement, target or current baseline invalid")

        # A real REST read of the exact iDempiere organisation/client ensures
        # the credentials and native IDs are not invented by this registry.
        try:
            engine = self.engine_for(e.ad_client_id, e.ad_org_id)
            if engine is None:
                raise ValueError()
            org = engine.get_record("AD_Org", e.ad_org_id)
            client = engine.get_record("AD_Client", e.ad_client_id)
            if (not isinstance(org, dict) or not isinstance(client, dict)
                    or _native_id(org.get("AD_Client_ID")) != e.ad_client_id
                    or _native_id(org.get("id")) != e.ad_org_id
                    or _native_id(client.get("id")) != e.ad_client_id
                    or org.get("IsActive") not in (True, "Y")
                    or client.get("IsActive") not in (True, "Y")):
                raise ValueError()
        except (ValueError, IdempiereClientError, TypeError, KeyError) as exc:
            raise LegalActorNotAuthorised("iDempiere native provider not ready") from None


class InboxAuthorityComposition:
    """Current IAM/CP checks, bound to one operator provisioned event context."""

    def __init__(self, registry: OperatorAuthorityRegistry,
                 connection: psycopg.Connection, engine_for: Callable,
                 cp_base: str, token_provider: Callable[[], str]):
        self.registry, self.db, self.engine_for = registry, connection, engine_for
        self.cp_base, self.token_provider = cp_base, token_provider

    def for_claim(self, claim: Claim) -> InboxNativeAuthority | None:
        entry = self.registry.for_claim(claim)
        if entry is None:
            return None
        correlation = lambda: claim.correlation_id or str(uuid.uuid4())
        operation = LegalActorOperation(
            context_id=entry.context_id, tenant_id=entry.tenant_id,
            operating_organisation_id=entry.operating_organisation_id,
            expected_legal_entity_id=entry.legal_entity_id,
            role="CONTRACTING_PARTY", activity=entry.activity,
            market=entry.market, capability=entry.capability,
            operation_reference=entry.commerce_order_id)
        policy = NativeActionPolicy(
            action="create_sales_order", activity=entry.activity,
            capability=entry.capability,
            authority_reference=entry.authority_reference)
        return InboxNativeAuthority(
            operation=operation, policy=policy,
            assessor=HttpControlPlaneLegalActorAssessor(
                self.cp_base, self.token_provider, correlation),
            documentary=HttpControlPlaneDocumentaryRestrictionAssessor(
                self.cp_base, self.token_provider, correlation),
            provider=NativeOrderProviderReadiness(self.db, self.engine_for, entry))


def from_operator_configuration(connection: psycopg.Connection, engine_for: Callable):
    """Missing configuration leaves the production worker DENYING every order."""
    path = os.environ.get("BAOBAB_ERP_INBOX_AUTHORITY_REGISTRY_FILE")
    if not path:
        return None
    # A local operator file is the DEVELOPMENT composition route only.
    # Production requires independent provider certification and deployment
    # approval, not a copied development registry file.
    if os.environ.get("BAOBAB_ENVIRONMENT", "") not in ("development", "test", "integration"):
        raise RuntimeError("DEV11_OPERATOR_REGISTRY_NOT_PRODUCTION_AUTHORITY")
    names = (
        "BAOBAB_ERP_CP_URL", "BAOBAB_ERP_CP_OAUTH_TOKEN_URL",
        "BAOBAB_ERP_CP_WORKLOAD_CLIENT_ID", "BAOBAB_ERP_CP_WORKLOAD_SECRET_FILE",
    )
    if any(not os.environ.get(name) for name in names):
        raise RuntimeError("DEV11_OPERATOR_CP_WORKLOAD_CONFIGURATION_INCOMPLETE")
    client_secret = _secure_text(os.environ[names[3]], limit=4096).strip()
    if len(client_secret) < 24:
        raise RuntimeError("DEV11_OPERATOR_CP_WORKLOAD_SECRET_INVALID")
    target = urllib.parse.urlsplit(os.environ[names[1]])
    if (not target.netloc or target.username or target.password
            or target.fragment or target.query
            or (target.scheme != "https" and not (
                target.scheme == "http" and target.hostname in ("localhost", "127.0.0.1", "::1")))):
        raise RuntimeError("DEV11_OPERATOR_OAUTH_TOKEN_URL_NOT_SECURE")
    token_provider = ClientCredentialsTokenProvider(
        os.environ[names[1]], os.environ[names[2]], client_secret,
        "legal-actor:assess documentary:restriction-assess",
        opener=urllib.request.build_opener(RejectRedirect()))
    return InboxAuthorityComposition(
        OperatorAuthorityRegistry(path), connection, engine_for,
        os.environ[names[0]], token_provider)
