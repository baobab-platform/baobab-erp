"""The ERP provisioning command body (Shared erp/v1 ``provisioning-request.schema.json``), parsed strictly.

The member set is closed and the grammars are Shared's, so the runtime needs no JSON Schema engine; the conformance suite
holds this parser to the schema at the pin. Requested countries and currencies are intent, never authority: they are
compared with what the approved plan and the Finance baseline say, they do not widen or choose anything.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

_CONTEXT = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_TENANT = re.compile(r"^tn_[a-z0-9]+$")
_PROVISIONING = re.compile(r"^tp_[a-z0-9]+$")
_PLAN = re.compile(r"^plan_[a-z0-9]+$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LEGAL_ENTITY = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def is_tenant_id(value: object) -> bool:
    """Whether ``value`` is a well-formed Control Plane tenantId (the grammar ``tenant_id`` is parsed with below)."""
    return isinstance(value, str) and 6 <= len(value) <= 63 and _TENANT.fullmatch(value) is not None

_MEMBERS = frozenset({"tenant_id", "context_id", "control_plane_authority", "legal_entity_ids", "finance_baselines", "requested_countries",
                      "functional_currencies", "deployment_policy_id", "localisation_profile_ids"})
_REQUIRED = frozenset({"tenant_id", "context_id", "control_plane_authority", "legal_entity_ids", "finance_baselines",
                       "requested_countries", "functional_currencies"})
_AUTHORITY = frozenset({"tenant_provisioning_id", "plan_id", "plan_version", "plan_digest"})
_BASELINE_REFERENCE = frozenset({"baseline_id", "legal_entity_id", "version", "digest", "effective_from", "authority"})
_BASELINE_AUTHORITY = {"engine_id": "baobab-erp", "system_of_record": "FINANCE_BASELINE"}
_BASELINE_ID = re.compile(r"^fb_[a-z0-9]+$")
_DATE = re.compile(r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$")


class RequestError(ValueError):
    """The body is not a valid provisioning command. ``errors`` names each offending member."""

    def __init__(self, errors: list[tuple[str, str]]):
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class ControlPlaneAuthority:
    tenant_provisioning_id: str
    plan_id: str
    plan_version: int
    plan_digest: str


@dataclass(frozen=True, slots=True)
class FinanceBaselineRef:
    """A Shared erp/v1 FinanceBaselineReference: the exact approved baseline version a provisioning relies on."""
    baseline_id: str
    legal_entity_id: str
    version: int
    digest: str
    effective_from: str

    def as_contract(self) -> dict:
        return {"baseline_id": self.baseline_id, "legal_entity_id": self.legal_entity_id, "version": self.version,
                "digest": self.digest, "effective_from": self.effective_from,
                "authority": dict(_BASELINE_AUTHORITY)}


@dataclass(frozen=True, slots=True)
class ProvisioningCommand:
    tenant_id: str
    context_id: str
    authority: ControlPlaneAuthority
    legal_entity_ids: tuple[str, ...]
    requested_countries: frozenset[str]
    functional_currencies: frozenset[str]
    deployment_policy_id: str | None
    localisation_profile_ids: frozenset[str]
    finance_baselines: tuple[FinanceBaselineRef, ...] = ()

    def fingerprint(self, principal: str) -> str:
        """Binds an Idempotency-Key to the authorised principal and the canonical request semantics (Shared idempotency
        policy): context_id is fresh authorization evidence and is excluded; list order and duplicates in sets do not change it, a different principal, tenant or content does."""
        canonical = {
            "principal": principal, "tenant_id": self.tenant_id,
            "authority": [self.authority.tenant_provisioning_id, self.authority.plan_id,
                          self.authority.plan_version, self.authority.plan_digest],
            "legal_entity_ids": sorted(self.legal_entity_ids),
            "finance_baselines": sorted((ref.as_contract() for ref in self.finance_baselines), key=lambda r: r["legal_entity_id"]),
            "requested_countries": sorted(self.requested_countries),
            "functional_currencies": sorted(self.functional_currencies),
            "deployment_policy_id": self.deployment_policy_id,
            "localisation_profile_ids": sorted(self.localisation_profile_ids),
        }
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text(value: Any, pattern: re.Pattern, field: str, errors: list, low: int = 1, high: int = 128) -> str | None:
    if not isinstance(value, str) or not (low <= len(value) <= high) or not pattern.fullmatch(value):
        errors.append((field, "does not match the canonical grammar"))
        return None
    return value


def _set(value: Any, pattern: re.Pattern, field: str, errors: list, *, minimum: int, low: int = 1, high: int = 128):
    if not isinstance(value, list) or len(value) < minimum:
        errors.append((field, f"must be a list of at least {minimum}"))
        return []
    if len(set(map(str, value))) != len(value):
        errors.append((field, "must not repeat a value"))
    return [item for item in (_text(v, pattern, f"{field}[{i}]", errors, low, high) for i, v in enumerate(value)) if item]


def _baseline_refs(value: Any, errors: list) -> list[FinanceBaselineRef]:
    """Strictly parses finance_baselines (Shared FinanceBaselineReference): a closed member set, ERP as the one authority, and
    no legal entity referenced twice. Whether each reference is what ERP holds is the handler's business, not the grammar's."""
    if not isinstance(value, list) or not value:
        errors.append(("finance_baselines", "must be a list of at least 1"))
        return []
    refs: list[FinanceBaselineRef] = []
    for index, item in enumerate(value):
        where = f"finance_baselines[{index}]"
        if not isinstance(item, Mapping):
            errors.append((where, "must be an object"))
            continue
        for field in sorted(set(item) - _BASELINE_REFERENCE):
            errors.append((f"{where}.{field}", "is not a member of a Finance baseline reference"))
        for field in sorted(_BASELINE_REFERENCE - set(item)):
            errors.append((f"{where}.{field}", "is required"))
        before = len(errors)
        baseline_id = _text(item.get("baseline_id"), _BASELINE_ID, f"{where}.baseline_id", errors, 6, 63)
        entity = _text(item.get("legal_entity_id"), _LEGAL_ENTITY, f"{where}.legal_entity_id", errors, 3, 63)
        digest = _text(item.get("digest"), _DIGEST, f"{where}.digest", errors, 71, 71)
        effective = _text(item.get("effective_from"), _DATE, f"{where}.effective_from", errors, 10, 10)
        if effective:
            try:
                date.fromisoformat(effective)
            except ValueError:
                errors.append((f"{where}.effective_from", "is not a calendar date"))
                effective = None
        version = item.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            errors.append((f"{where}.version", "must be an integer >= 1"))
        if item.get("authority") != _BASELINE_AUTHORITY:
            errors.append((f"{where}.authority", "must be exactly baobab-erp as the FINANCE_BASELINE system of record"))
        if len(errors) == before and baseline_id and entity and digest and effective:
            refs.append(FinanceBaselineRef(baseline_id, entity, version, digest, effective))
    if len({ref.legal_entity_id for ref in refs}) != len(refs):
        errors.append(("finance_baselines", "must not reference a legal entity twice"))
    return refs


def parse_command(body: Any) -> ProvisioningCommand:
    errors: list[tuple[str, str]] = []
    if not isinstance(body, Mapping):
        raise RequestError([("body", "must be a JSON object")])
    for field in sorted(set(body) - _MEMBERS):
        errors.append((field, "is not a member of the provisioning request"))
    for field in sorted(_REQUIRED - set(body)):
        errors.append((field, "is required"))
    tenant = _text(body.get("tenant_id"), _TENANT, "tenant_id", errors, 6, 63) if "tenant_id" in body else None
    context_id = _text(body.get("context_id"), _CONTEXT, "context_id", errors, 36, 36) if "context_id" in body else None
    authority = None
    raw = body.get("control_plane_authority")
    if "control_plane_authority" in body:
        if not isinstance(raw, Mapping):
            errors.append(("control_plane_authority", "must be an object"))
        else:
            for field in sorted(set(raw) - _AUTHORITY):
                errors.append((f"control_plane_authority.{field}", "is not a member"))
            for field in sorted(_AUTHORITY - set(raw)):
                errors.append((f"control_plane_authority.{field}", "is required"))
            version = raw.get("plan_version")
            if "plan_version" in raw and (isinstance(version, bool) or not isinstance(version, int) or version < 1):
                errors.append(("control_plane_authority.plan_version", "must be an integer >= 1"))
            ids = (_text(raw.get("tenant_provisioning_id"), _PROVISIONING, "control_plane_authority.tenant_provisioning_id", errors, 6, 63),
                   _text(raw.get("plan_id"), _PLAN, "control_plane_authority.plan_id", errors, 8, 63),
                   _text(raw.get("plan_digest"), _DIGEST, "control_plane_authority.plan_digest", errors, 71, 71))
            if all(ids) and isinstance(version, int) and not isinstance(version, bool) and version >= 1 \
                    and not set(raw) - _AUTHORITY:
                authority = ControlPlaneAuthority(ids[0], ids[1], version, ids[2])
    entities = _set(body.get("legal_entity_ids"), _LEGAL_ENTITY, "legal_entity_ids", errors, minimum=1, low=3, high=63) \
        if "legal_entity_ids" in body else []
    baselines = _baseline_refs(body.get("finance_baselines"), errors) if "finance_baselines" in body else []
    countries = _set(body.get("requested_countries"), _COUNTRY, "requested_countries", errors, minimum=1, low=2, high=2) \
        if "requested_countries" in body else []
    currencies = _set(body.get("functional_currencies"), _CURRENCY, "functional_currencies", errors, minimum=1, low=3, high=3) \
        if "functional_currencies" in body else []
    policy = None
    if "deployment_policy_id" in body:
        policy = _text(body["deployment_policy_id"], _RESOURCE, "deployment_policy_id", errors, 3, 128)
    profiles = _set(body["localisation_profile_ids"], _RESOURCE, "localisation_profile_ids", errors, minimum=0, low=3) \
        if "localisation_profile_ids" in body else []
    if errors:
        raise RequestError(errors)
    return ProvisioningCommand(tenant_id=tenant, context_id=context_id, authority=authority, legal_entity_ids=tuple(entities),
                               requested_countries=frozenset(countries), functional_currencies=frozenset(currencies),
                               deployment_policy_id=policy, localisation_profile_ids=frozenset(profiles),
                               finance_baselines=tuple(baselines))
