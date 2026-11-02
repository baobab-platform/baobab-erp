"""Disposable *real iDempiere JVM* transport for DEV-11 order qualification.

The normal production endpoint is RestIdempiereClient, but its separately
provisioned REST OSGi plugin is absent from the engine-local acceptance image.
This adapter instead submits one narrowly scoped test request to the ALREADY
INSTALLED real GateDDriver OSGi bundle in iDempiere 13. Its mutation occurs
INSIDE the native JVM with the protected CP finance veto and JDBC commit fence.

Every read is from the native PostgreSQL 17 database, never a simulated API.
No other document, company, currency, endpoint or arbitrary SQL is exposed.
Enabled only on explicitly disposable integration/test processes. No staging,
production, application-server HTTP endpoint or general Baobab engine transport.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import re
import stat
import time
import uuid

import psycopg
from psycopg.rows import dict_row

from integration.idempiere_client import Eq, IdempiereClientError

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,126}$")
_INT = re.compile(r"^[1-9][0-9]{0,10}$")
_PRICE = re.compile(r"^[0-9]+(?:\.[0-9]{1,4})?$")
MAX_WAIT_SECONDS = 180


def _positive(value, name):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not _INT.fullmatch(value):
        raise IdempiereClientError("DEV11_NATIVE_" + name + "_INVALID")
    return int(value)


def _private_driver_dir(raw: str):
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise IdempiereClientError("DEV11_GATE_DRIVER_DIRECTORY_INVALID")
    for child in ("ready", "requests", "results"):
        file = path / child
        if file.is_symlink() or not file.exists():
            raise IdempiereClientError("DEV11_GATE_DRIVER_NOT_READY")
    if not (path / "ready").is_file():
        raise IdempiereClientError("DEV11_GATE_DRIVER_NOT_READY")
    return path


class RealJvmGateDOrderAdapter:
    """Only C_Order on exact GardenWorld client/org, one native sales line."""

    def __init__(self, client_id: int, org_id: int, *, db_url: str, driver_dir: str):
        if (os.environ.get("BAOBAB_ENVIRONMENT") != "integration" or
                os.environ.get("BAOBAB_ERP_INBOX_PROFILE") != "dev11-order-placed" or
                os.environ.get("BAOBAB_REQUIRE_LEGAL_ACTOR_GATE", "").lower() != "true" or
                os.environ.get("BAOBAB_DEV11_REAL_JVM_GATE_ENABLED") != "true" or
                os.environ.get("BAOBAB_DEPLOYMENT_ENV", "") in ("staging", "production") or
                client_id != 11 or org_id != 11):
            raise IdempiereClientError("DEV11_NATIVE_JVM_GATE_NOT_AUTHORISED")
        if not db_url:
            raise IdempiereClientError("DEV11_NATIVE_DB_REQUIRED")
        self.client_id, self.org_id = client_id, org_id
        self.database = db_url
        self.driver = _private_driver_dir(driver_dir)

    def _sql(self, sql, params):
        # READ ONLY real iDempiere database, not PostgreSQL writes disguised
        # as an engine adapter. JVM owns every native mutation.
        try:
            with psycopg.connect(self.database, autocommit=True, row_factory=dict_row) as db:
                db.execute("BEGIN ISOLATION LEVEL READ COMMITTED READ ONLY")
                rows = db.execute(sql, params).fetchall()
                db.execute("COMMIT")
                return rows
        except psycopg.Error:
            raise IdempiereClientError("DEV11_NATIVE_READ_UNAVAILABLE") from None

    def get_record(self, table: str, record_id: int):
        record_id = _positive(record_id, "RECORD_ID")
        selections = {
            "AD_Org": ("SELECT ad_org_id AS id, ad_client_id, isactive "
                       "FROM adempiere.ad_org WHERE ad_org_id=%s"),
            "AD_Client": ("SELECT ad_client_id AS id, isactive "
                          "FROM adempiere.ad_client WHERE ad_client_id=%s"),
            "M_Product": ("SELECT m_product_id AS id, c_uom_id, ad_client_id, isactive "
                           "FROM adempiere.m_product WHERE m_product_id=%s"),
            "C_UOM": ("SELECT c_uom_id AS id, x12de355 "
                      "FROM adempiere.c_uom WHERE c_uom_id=%s"),
            "C_Order": ("SELECT c_order_id AS id, ad_client_id, ad_org_id, poreference, issotrx "
                       "FROM adempiere.c_order WHERE c_order_id=%s"),
        }
        query = selections.get(table)
        if query is None:
            raise IdempiereClientError("DEV11_NATIVE_READ_TABLE_NOT_ALLOWED")
        rows = self._sql(query, (record_id,))
        if len(rows) != 1:
            raise IdempiereClientError("DEV11_NATIVE_RECORD_MISSING")
        row = rows[0]
        if table == "AD_Org":
            return {"id": row["id"], "AD_Client_ID": {"id": row["ad_client_id"]},
                    "IsActive": row["isactive"]}
        if table == "AD_Client":
            return {"id": row["id"], "IsActive": row["isactive"]}
        if table == "M_Product":
            return {"id": row["id"], "C_UOM_ID": {"id": row["c_uom_id"]},
                    "AD_Client_ID": {"id": row["ad_client_id"]},
                    "IsActive": row["isactive"]}
        if table == "C_UOM":
            return {"id": row["id"], "X12DE355": row["x12de355"]}
        return {"id": row["id"], "AD_Client_ID": {"id": row["ad_client_id"]},
                "AD_Org_ID": {"id": row["ad_org_id"]},
                "POReference": row["poreference"], "IsSOTrx": row["issotrx"]}

    def query(self, table, conditions, select):
        if (table != "C_Order" or len(conditions) != 1 or
                not isinstance(conditions[0], Eq) or
                conditions[0].column != "POReference" or
                not isinstance(conditions[0].value, str) or
                not _REF.fullmatch(conditions[0].value) or
                list(select) != ["C_Order_ID"]):
            raise IdempiereClientError("DEV11_NATIVE_QUERY_NOT_ALLOWED")
        # Deliberately DO NOT filter to the expected AD_Client: a duplicate
        # across a foreign company must be seen and rejected, not hidden.
        rows = self._sql(
            """SELECT c_order_id AS id, ad_client_id, ad_org_id, poreference
                 FROM adempiere.c_order WHERE poreference=%s""",
            (conditions[0].value,))
        return [dict(row) for row in rows]

    def _readback(self, native_id, fields):
        expected_lines = fields["OrderLines"]
        order = self._sql(
            """SELECT o.c_order_id, o.ad_client_id, o.ad_org_id, o.c_bpartner_id,
                      o.poreference, o.issotrx, c.iso_code
                 FROM adempiere.c_order o
                 JOIN adempiere.c_currency c ON c.c_currency_id=o.c_currency_id
                WHERE o.c_order_id=%s""", (native_id,))
        if len(order) != 1:
            raise IdempiereClientError("DEV11_NATIVE_ORDER_NOT_COMMITTED")
        o = order[0]
        lines = self._sql(
            """SELECT m_product_id, qtyordered, priceentered
                 FROM adempiere.c_orderline WHERE c_order_id=%s
                 ORDER BY c_orderline_id""", (native_id,))
        expected = expected_lines[0]
        if (o["ad_client_id"] != self.client_id or o["ad_org_id"] != self.org_id
                or o["c_bpartner_id"] != fields["C_BPartner_ID"]
                or o["poreference"] != fields["POReference"]
                or o["issotrx"] != "Y" or o["iso_code"] != fields["CurrencyISO"]
                or len(lines) != 1 or
                lines[0]["m_product_id"] != _positive(expected["M_Product_ID"], "SKU_ID")
                or Decimal(str(lines[0]["qtyordered"])) != Decimal(expected["QtyOrdered"])
                or Decimal(str(lines[0]["priceentered"])) != Decimal(expected["PriceEntered"])):
            raise IdempiereClientError("DEV11_NATIVE_BUSINESS_FACTS_MISMATCH")
        return native_id

    def assert_existing_order_matches(self, native_id, order, customer, lines):
        # The native order is durable from an earlier uncertain attempt.
        # Prove company, client, legal reference and every line BEFORE
        # adopting it. Never turn a matching POReference into authority.
        from order_to_cash.service import sales_order_fields
        if not hasattr(order, "commerce_order_id") or len(lines) != 1:
            raise IdempiereClientError("DEV11_NATIVE_ADOPTION_SCOPE_INVALID")
        fields = sales_order_fields(
            customer, order.currency, lines, reference=order.commerce_order_id)
        return self._readback(native_id, fields)

    def create_record(self, table, fields):
        if table != "C_Order" or not isinstance(fields, dict):
            raise IdempiereClientError("DEV11_NATIVE_CREATE_NOT_ALLOWED")
        allowed = {"C_BPartner_ID", "CurrencyISO", "OrderLines", "POReference"}
        if set(fields) != allowed or fields["CurrencyISO"] != "USD" or (
                not isinstance(fields["POReference"], str)
                or not _REF.fullmatch(fields["POReference"])):
            raise IdempiereClientError("DEV11_NATIVE_CREATE_CONTRACT_INVALID")
        lines = fields["OrderLines"]
        if not isinstance(lines, list) or len(lines) != 1 or set(lines[0]) != {
            "M_Product_ID", "QtyOrdered", "PriceEntered",
        }:
            raise IdempiereClientError("DEV11_NATIVE_SINGLE_LINE_REQUIRED")
        line = lines[0]
        customer = _positive(fields["C_BPartner_ID"], "CUSTOMER")
        product = _positive(line["M_Product_ID"], "PRODUCT")
        try:
            quantity, price = Decimal(str(line["QtyOrdered"])), Decimal(str(line["PriceEntered"]))
        except InvalidOperation:
            raise IdempiereClientError("DEV11_NATIVE_AMOUNT_INVALID") from None
        if (quantity <= 0 or quantity > 1000 or price < 0 or price > 1_000_000
                or len(str(quantity)) > 20 or len(str(price)) > 20
                or not _PRICE.fullmatch(str(price))):
            raise IdempiereClientError("DEV11_NATIVE_AMOUNT_INVALID")
        # No caller-selected product/partner is honoured by the Java fixture.
        # The Java driver asserts both IDs match its native GardenWorld seed.
        params = {
            "action": "doc", "kind": "order", "dev11_profile": "signed-event-erp",
            "org": "11", "reference": fields["POReference"], "complete": "false",
            "post": "false", "qty": str(quantity), "unit_price": str(price),
            "expected_customer": str(customer), "expected_product": str(product),
        }
        name = "dev11-" + uuid.uuid4().hex
        pending = self.driver / "requests" / (name + ".properties")
        ready = self.driver / "results" / (name + ".properties")
        temp = self.driver / "requests" / (name + ".tmp")
        if pending.exists() or ready.exists() or temp.exists():
            raise IdempiereClientError("DEV11_NATIVE_DISPOSABLE_COLLISION")
        # Exclusive file creation prevents accidental fixture replacement.
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as output:
                for key, value in params.items():
                    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", value):
                        raise IdempiereClientError("DEV11_NATIVE_DRIVER_PROPERTY_INVALID")
                    output.write(key + "=" + value + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, pending)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

        end = time.monotonic() + MAX_WAIT_SECONDS
        while time.monotonic() < end:
            if ready.is_file() and not ready.is_symlink():
                data = {}
                for line_text in ready.read_text(encoding="utf-8").splitlines():
                    if line_text.startswith("#") or line_text.startswith("!"):
                        continue
                    if "=" in line_text:
                        key, value = line_text.split("=", 1)
                        data[key.strip()] = value.strip()
                ready.unlink(missing_ok=True)
                if ("error" in data or "driver_error" in data
                        or data.get("committed") != "true"):
                    raise IdempiereClientError("DEV11_NATIVE_JVM_VETO_OR_COMMIT_DENIED")
                native_id = _positive(data.get("id"), "CREATED_ORDER")
                observed = self._readback(native_id, fields)
                # DISPOSABLE REAL-ENGINE fault: the JVM actually committed
                # and the independent native query already verified it, but
                # the Python ERP worker loses its *application-level* result
                # before writing its own execution/outbox receipt. This tests
                # cross-transaction unknown-outcome adoption, not a mock.
                if (os.environ.get("BAOBAB_DEV11_NATIVE_UNKNOWN_AFTER_COMMIT") == "true"
                        and os.environ.get("BAOBAB_ENVIRONMENT") == "integration"
                        and os.environ.get("BAOBAB_DEV11_REAL_JVM_GATE_ENABLED") == "true"):
                    raise IdempiereClientError("DEV11_NATIVE_JVM_RESULT_UNKNOWN")
                return observed
            time.sleep(.25)
        # UNKNOWN OUTCOME: the JVM may commit after this process loses the
        # reply; never retry a *different* order. The ERP executor must find
        # the same POReference before any subsequent creation attempt.
        raise IdempiereClientError("DEV11_NATIVE_JVM_RESULT_UNKNOWN")
