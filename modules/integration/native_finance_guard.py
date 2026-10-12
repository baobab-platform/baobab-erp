"""LA-05 ERP: second, fail-closed policy-enforcement point at native REST egress.

Application-level governed O2C wrappers are necessary but insufficient: direct
RestIdempiereClient.create_record/execute_process can bypass them. This gate
runs before HTTP authentication/network I/O, independently of the caller's
claimed context, and accepts ONLY the private, already-governed command scope.

This is not an iDempiere JVM ModelValidator: separate direct access to native
iDempiere (including its UI/batch processes) must remain blocked until a native
server-side PEP has been installed and certified.
"""
from __future__ import annotations

from collections.abc import Mapping
import os
from urllib.parse import urlsplit

from integration.idempiere_client import IdempiereClientError, IdempiereCredentials

class NativeFinancialMutationDenied(IdempiereClientError):
    """Missing or mismatched authority for a native financial mutation."""


# Native finance data can neither be created by a blind REST request nor
# rewritten as an alternative to governed document processing/reversal.
_FINANCE_TABLES = frozenset({
    "C_ORDER", "C_ORDERLINE", "M_INOUT", "M_INOUTLINE",
    "C_INVOICE", "C_INVOICELINE", "C_PAYMENT", "C_PAYMENTALLOCATE",
    "C_ALLOCATIONHDR", "C_ALLOCATIONLINE", "FACT_ACCT",
    "GL_JOURNAL", "GL_JOURNALLINE", "C_BANKSTATEMENT",
    "C_BANKSTATEMENTLINE", "C_CASH", "C_CASHLINE",
    "C_ACCTSCHEMA", "C_PERIOD", "C_YEAR", "C_CALENDAR",
    "C_CONVERSION_RATE", "C_TAX", "C_TAXCATEGORY",
})
_CREATION_ACTIONS = {
    "C_ORDER": "create_sales_order",
    "M_INOUT": "create_shipment",
    "C_INVOICE": "create_customer_invoice",
    "C_PAYMENT": "create_payment",
}
_PROCESS_ID_ENV = {
    "complete_sales_order": "IDEMPIERE_PROCESS_COMPLETE_SALES_ORDER",
    "complete_shipment": "IDEMPIERE_PROCESS_COMPLETE_SHIPMENT",
    "post_customer_invoice": "IDEMPIERE_PROCESS_POST_CUSTOMER_INVOICE",
    "complete_payment": "IDEMPIERE_PROCESS_COMPLETE_PAYMENT",
    "allocate_payment": "IDEMPIERE_PROCESS_ALLOCATE_PAYMENT",
}
_COMPLETE_ACTIONS = {
    "C_Order_ID": "complete_sales_order",
    "M_InOut_ID": "complete_shipment",
    "C_Invoice_ID": "post_customer_invoice",
    "C_Payment_ID": "complete_payment",
}


def _denied() -> None:
    # No tenant, legal actor, mandate or token metadata in protocol errors.
    raise NativeFinancialMutationDenied(
        "native finance action blocked: scoped ERP legal actor and "
        "verified company readiness required"
    )


def _company_bound(marker: tuple | None, credentials: IdempiereCredentials) -> bool:
    return bool(
        marker and len(marker) >= 5
        and marker[-2] == credentials.client_id
        and marker[-1] == credentials.organization_id
        and isinstance(marker[0], str) and marker[0]
        and isinstance(marker[1], str) and marker[1]
    )


def _valid_record_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def require_native_financial_authority(
    method: str, path: str, body: Mapping[str, object] | None,
    credentials: IdempiereCredentials,
) -> None:
    """Require the real governed action marker and exact native company.

    The marker is created by the existing CP/documentary/native-readiness
    composition after final re-assessment. A client-passed role, tenant,
    `governed=true`, or process number cannot create it.
    """
    from order_to_cash.service import (
        _protected_finance_runtime, _invoice_post_execution,
        _native_action_execution,
    )

    if not _protected_finance_runtime() or method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    target = urlsplit(path)
    parts = target.path.strip("/").split("/")
    if not parts or parts[0] not in {"models", "processes"}:
        return
    if target.query or target.fragment or target.path.endswith("/") or "%" in target.path:
        _denied()
    data = body if isinstance(body, Mapping) else {}
    native = _native_action_execution.get()
    invoice = _invoice_post_execution.get()

    if parts[0] == "models":
        if len(parts) < 2:
            _denied()
        table = parts[1].upper()
        if table not in _FINANCE_TABLES:
            return
        # Edits/deletes to financial facts are never a normal REST operation.
        # Nor may a caller create GL, allocation, tax or finance-baseline rows
        # through this consumer; those require separate governed workflows.
        if method != "POST" or len(parts) != 2:
            _denied()
        action = _CREATION_ACTIONS.get(table)
        if not action or not _company_bound(native, credentials) or native[2] != action:
            _denied()
        # Never set posted/completed state in a model creation payload.
        # Financial status transitions use the governed native processes.
        if any(str(key).upper() in {"DOCSTATUS", "DOCACTION", "POSTED", "PROCESSED"}
               for key in data):
            _denied()
        # Native REST credentials are not permission to override company scope.
        for field, expected in (("AD_Client_ID", credentials.client_id),
                                ("AD_Org_ID", credentials.organization_id)):
            if field in data and (isinstance(data[field], bool) or data[field] != expected):
                _denied()
        return

    # Process IDs are installation-specific and are NOT a safe way to tell
    # a posting process from a different privileged financial process. Every
    # process through this client must carry a known governed O2C operation.
    if method != "POST" or len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        _denied()
    present = [key for key in _COMPLETE_ACTIONS if key in data]
    if not present or any(not _valid_record_id(data[k]) for k in present):
        _denied()
    if set(present) == {"C_Invoice_ID", "C_Payment_ID"}:
        action = "allocate_payment"
        if "DocAction" in data or not isinstance(data.get("Amount"), (str, int)):
            _denied()
    elif len(present) == 1:
        action = _COMPLETE_ACTIONS[present[0]]
        if data.get("DocAction") != "CO":
            _denied()
    else:
        _denied()
    configured_process_id = os.environ.get(_PROCESS_ID_ENV[action], "")
    if (not configured_process_id.isdigit()
            or int(configured_process_id) <= 0
            or int(configured_process_id) != int(parts[1])):
        _denied()
    if action == "post_customer_invoice":
        if not _company_bound(invoice, credentials):
            _denied()
    elif not _company_bound(native, credentials) or native[2] != action:
        _denied()
