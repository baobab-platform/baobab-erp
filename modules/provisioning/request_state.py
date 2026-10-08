"""Reads a provisioning request back from the desired state stored with its operation.

An operation is accepted (``command_store.accept``) by one process and executed by another, so the request has to survive storage
exactly. ``planner.desired_state_json`` is the one serialisation (sets as sorted lists, dates as ISO text); this module is its
inverse. Fidelity is never assumed: the executor recomputes the plan digest from the decoded request and refuses to run when it
differs from the digest the operation was accepted under (``StateDrift``), so a lossy or edited row fails closed rather than
provisioning something other than what was approved.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from provisioning.model import AccountingConfiguration, ErpProvisioningRequest, MarketConfiguration
from provisioning.planner import desired_state_digest


class StateUnreadable(Exception):
    """The stored desired state is not a provisioning request this code can read."""


class StateDrift(Exception):
    """The stored desired state does not reproduce the digest the operation was accepted under."""


def _market(raw: Mapping[str, Any]) -> MarketConfiguration:
    return MarketConfiguration(
        market_id=raw["market_id"], country_code=raw["country_code"],
        participation_capabilities=frozenset(raw["participation_capabilities"]), currencies=tuple(raw["currencies"]),
        localisation_profile=raw["localisation_profile"], warehouse_codes=tuple(raw.get("warehouse_codes", ())),
        warehouse_timezones=tuple((code, zone) for code, zone in raw.get("warehouse_timezones", ())))


def _accounting(raw: Mapping[str, Any]) -> AccountingConfiguration:
    return AccountingConfiguration(
        functional_currency=raw["functional_currency"], fiscal_year_start_month=int(raw["fiscal_year_start_month"]),
        chart_of_accounts_template=raw["chart_of_accounts_template"], accounting_schema=raw["accounting_schema"],
        tax_profile=raw["tax_profile"], costing_method=raw["costing_method"], approved_by=raw["approved_by"],
        approved_at=datetime.fromisoformat(raw["approved_at"]))


def request_from_state(state: Mapping[str, Any]) -> ErpProvisioningRequest:
    try:
        return ErpProvisioningRequest(
            provisioning_id=state["provisioning_id"], idempotency_key=state["idempotency_key"], tenant_id=state["tenant_id"],
            legal_entity_id=state["legal_entity_id"], legal_name=state["legal_name"],
            registration_identifier=state["registration_identifier"], jurisdiction_code=state["jurisdiction_code"],
            engine_instance_id=state["engine_instance_id"], isolation_requirement=state["isolation_requirement"],
            plan_digest=state["plan_digest"], target_environment=state["target_environment"],
            effective_date=date.fromisoformat(state["effective_date"]), accounting=_accounting(state["accounting"]),
            markets=tuple(_market(market) for market in state["markets"]),
            requested_capabilities=frozenset(state.get("requested_capabilities", ())))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StateUnreadable(f"{type(exc).__name__}: {exc}") from exc


def verified_request(state: Mapping[str, Any], accepted_digest: str | None) -> ErpProvisioningRequest:
    """The request, proven to be the one the operation was accepted under."""
    request = request_from_state(state)
    if not accepted_digest or desired_state_digest(request) != accepted_digest:
        raise StateDrift("the stored desired state does not reproduce the operation's plan digest")
    return request
