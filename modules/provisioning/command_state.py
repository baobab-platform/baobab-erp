"""The contract-level state of a provisioning command, derived from its legal entities' own provisioning records.

A command provisions several legal entities, each with its own ERP provisioning record and status. The command's state
(erp/v1 ProvisioningState) is a pure function of those statuses, so it can never disagree with them and the same statuses
always give the same state. Failure carries a fixed code, never the entity's free-text error, which can name internals.
"""
from __future__ import annotations

from typing import Iterable

FAILED_CODE = "ERP_PROVISIONING_FAILED"

_DONE = {"ready", "active"}
_IN_FLIGHT = {"applying"}
_SETTLING = {"reconciling", "suspended"}
_NOT_STARTED = {"requested", "planned"}


def derive(statuses: Iterable[str]) -> tuple[str, str | None]:
    """(state, failure_code) of a command whose legal entities have these provisioning statuses."""
    seen = set(statuses)
    if not seen:
        raise ValueError("a provisioning command has at least one legal entity")
    unknown = seen - (_DONE | _IN_FLIGHT | _SETTLING | _NOT_STARTED | {"validating", "failed"})
    if unknown:
        raise ValueError(f"unknown provisioning status {sorted(unknown)}")
    if "failed" in seen:
        return "failed", FAILED_CODE
    if seen <= _DONE:
        return "active", None
    if seen & _IN_FLIGHT:
        return "provisioning", None
    if seen <= _NOT_STARTED:
        return "accepted", None
    if seen <= {"validating"} | _NOT_STARTED:
        return "validating", None
    if seen <= _DONE | _SETTLING:
        return "reconciling", None
    # Some entity has progressed while another has not started: the command is provisioning.
    return "provisioning", None
