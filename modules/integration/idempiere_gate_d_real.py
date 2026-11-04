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
from functools import wraps
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
_JVM_ID_MAX = 2_147_483_647
_NATIVE_ID_COLUMNS = frozenset({
    "id", "ad_client_id", "ad_org_id", "c_uom_id", "c_bpartner_id",
    "c_order_id", "c_orderline_id", "m_product_id",
})
_DIAGNOSTIC_FAILURES = {
    "DEV11_NATIVE_READ_UNAVAILABLE": "NATIVE_ENGINE_READ_UNAVAILABLE",
    "DEV11_NATIVE_RECORD_MISSING": "NATIVE_ENGINE_RECORD_MISSING",
    "DEV11_NATIVE_BUSINESS_FACTS_MISMATCH": "NATIVE_ENGINE_FACTS_MISMATCH",
    "DEV11_NATIVE_JVM_VETO_OR_COMMIT_DENIED": "NATIVE_JVM_COMMIT_DENIED",
    "DEV11_NATIVE_JVM_RESULT_UNKNOWN": "NATIVE_JVM_RESULT_UNKNOWN",
    "DEV11_NATIVE_DRIVER_PROPERTY_INVALID": "NATIVE_ENGINE_PROPERTY_REFUSED",
    "DEV11_NATIVE_CREATE_CONTRACT_INVALID": "NATIVE_ENGINE_CONTRACT_REFUSED",
    "DEV11_NATIVE_REFERENCE_TOO_LONG": "NATIVE_ENGINE_REFERENCE_REFUSED",
}
_DRIVER_REFUSALS = {
    "BAOBAB_NATIVE_FINANCE_DENIED": "NATIVE_JVM_FINANCE_VETO",
    "DEV11_NATIVE_PROTECTED_DRIVER_REQUIRED": "NATIVE_JVM_PROFILE_REFUSED",
    "DEV11_NATIVE_FIXTURE_MAPPING_MISMATCH": "NATIVE_JVM_FIXTURE_MISMATCH",
    "DEV11_NATIVE_PRICE_INVALID": "NATIVE_JVM_PRICE_REFUSED",
    "DEV11_ORDER_REFERENCE_INVALID": "NATIVE_JVM_REFERENCE_REFUSED",
}
_FACT_STAGES = frozenset({
    "NATIVE_FACT_CLIENT", "NATIVE_FACT_ORGANISATION", "NATIVE_FACT_CUSTOMER",
    "NATIVE_FACT_REFERENCE", "NATIVE_FACT_DIRECTION", "NATIVE_FACT_CURRENCY",
    "NATIVE_FACT_LINE_COUNT", "NATIVE_FACT_PRODUCT", "NATIVE_FACT_QUANTITY",
    "NATIVE_FACT_PRICE",
})
NATIVE_DIAGNOSTIC_STAGES = frozenset({
    "NATIVE_ENGINE_READ", "NATIVE_ENGINE_QUERY", "NATIVE_ENGINE_CREATE",
    "NATIVE_ENGINE_ADOPT", "NATIVE_ENGINE_CLIENT_FAILURE",
    *_DIAGNOSTIC_FAILURES.values(), *_DRIVER_REFUSALS.values(), *_FACT_STAGES,
})


def _native_uuid(value):
    try:
        return str(uuid.UUID(value)) == value and uuid.UUID(value).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


def _native_phase(stage):
    # Observe only a closed stage vocabulary in the explicitly private real
    # integration profile. Never publish native result text, SQL, IDs or args.
    if (stage in NATIVE_DIAGNOSTIC_STAGES
            and os.environ.get("BAOBAB_ENVIRONMENT") == "integration"
            and os.environ.get("DEV11_REAL_NATIVE_ACCEPTANCE") == "true"
            and os.environ.get("BAOBAB_DEV11_REAL_JVM_GATE_ENABLED") == "true"
            and os.environ.get("BAOBAB_DEPLOYMENT_ENV") not in ("staging", "production")):
        print("DEV11_NATIVE_AUTHORITY_STAGE " + stage, flush=True)


def _observed_native_call(stage):
    def decorate(method):
        @wraps(method)
        def observed(*args, **kwargs):
            _native_phase(stage)
            try:
                return method(*args, **kwargs)
            except IdempiereClientError as failure:
                _native_phase(_DIAGNOSTIC_FAILURES.get(
                    str(failure), "NATIVE_ENGINE_CLIENT_FAILURE"))
                raise  # Keep the exact native veto/unknown-outcome semantics.
        return observed
    return decorate


def _positive(value, name):
    # PostgreSQL NUMERIC identifiers arrive as Decimal. Preserve the native
    # REST-shaped integer interface without truncating fractions or accepting
    # bool/float IDs, non-finite values or numbers outside Java's int range.
    if type(value) in (int, Decimal):
        if (type(value) is Decimal and not value.is_finite()
                or not 0 < value <= _JVM_ID_MAX or value != int(value)):
            raise IdempiereClientError("DEV11_NATIVE_" + name + "_INVALID")
        value = str(int(value))
    if not isinstance(value, str) or not _INT.fullmatch(value):
        raise IdempiereClientError("DEV11_NATIVE_" + name + "_INVALID")
    result = int(value)
    if result > _JVM_ID_MAX:
        raise IdempiereClientError("DEV11_NATIVE_" + name + "_INVALID")
    return result


def _native_row(row):
    """Normalize only known identifier columns; business numbers stay exact."""
    return {key: _positive(value, "READ_ID") if key in _NATIVE_ID_COLUMNS else value
            for key, value in row.items()}


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

    @_observed_native_call("NATIVE_ENGINE_READ")
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
            "C_Order": ("SELECT c_order_id AS id, ad_client_id, ad_org_id, poreference, c_order_uu, issotrx "
                       "FROM adempiere.c_order WHERE c_order_id=%s"),
        }
        query = selections.get(table)
        if query is None:
            raise IdempiereClientError("DEV11_NATIVE_READ_TABLE_NOT_ALLOWED")
        rows = self._sql(query, (record_id,))
        if len(rows) != 1:
            raise IdempiereClientError("DEV11_NATIVE_RECORD_MISSING")
        row = _native_row(rows[0])
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
                "POReference": row["poreference"], "C_Order_UU": row.get("c_order_uu"), "IsSOTrx": row["issotrx"]}

    @_observed_native_call("NATIVE_ENGINE_QUERY")
    def query(self, table, conditions, select):
        if (table != "C_Order" or len(conditions) != 1 or
                not isinstance(conditions[0], Eq) or
                conditions[0].column not in ("POReference", "C_Order_UU") or
                not isinstance(conditions[0].value, str) or
                not _REF.fullmatch(conditions[0].value) or
                list(select) != ["C_Order_ID"]):
            raise IdempiereClientError("DEV11_NATIVE_QUERY_NOT_ALLOWED")
        # Deliberately DO NOT filter to the expected AD_Client: a duplicate
        # across a foreign company must be seen and rejected, not hidden.
        column = "c_order_uu" if conditions[0].column == "C_Order_UU" else "poreference"
        if column == "c_order_uu" and not _native_uuid(conditions[0].value):
            raise IdempiereClientError("DEV11_NATIVE_UUID_INVALID")
        rows = self._sql(
            "SELECT c_order_id AS id, ad_client_id, ad_org_id, poreference, c_order_uu "
            "FROM adempiere.c_order WHERE " + column + "=%s",
            (conditions[0].value,))
        return [_native_row(row) for row in rows]

    def _readback(self, native_id, fields):
        expected_lines = fields["OrderLines"]
        order = self._sql(
            """SELECT o.c_order_id, o.ad_client_id, o.ad_org_id, o.c_bpartner_id,
                      o.poreference, o.c_order_uu, o.issotrx, c.iso_code
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
        # Keep every exact business comparison. Only closed field categories
        # may identify a mismatch; actual native/expected values stay private.
        checks = {
            "NATIVE_FACT_CLIENT": o["ad_client_id"] == self.client_id,
            "NATIVE_FACT_ORGANISATION": o["ad_org_id"] == self.org_id,
            "NATIVE_FACT_CUSTOMER": o["c_bpartner_id"] == fields["C_BPartner_ID"],
            "NATIVE_FACT_REFERENCE": (o.get("c_order_uu") == fields["C_Order_UU"]
                if "C_Order_UU" in fields else o["poreference"] == fields["POReference"]),
            "NATIVE_FACT_DIRECTION": o["issotrx"] == "Y",
            "NATIVE_FACT_CURRENCY": o["iso_code"] == fields["CurrencyISO"],
            "NATIVE_FACT_LINE_COUNT": len(lines) == 1,
        }
        if len(lines) == 1:
            checks.update({
                "NATIVE_FACT_PRODUCT": lines[0]["m_product_id"] == _positive(expected["M_Product_ID"], "SKU_ID"),
                "NATIVE_FACT_QUANTITY": Decimal(str(lines[0]["qtyordered"])) == Decimal(expected["QtyOrdered"]),
                "NATIVE_FACT_PRICE": Decimal(str(lines[0]["priceentered"])) == Decimal(expected["PriceEntered"]),
            })
        if not all(checks.values()):
            for stage, matched in checks.items():
                if not matched:
                    _native_phase(stage)
            raise IdempiereClientError("DEV11_NATIVE_BUSINESS_FACTS_MISMATCH")
        return native_id

    @_observed_native_call("NATIVE_ENGINE_ADOPT")
    def assert_existing_order_matches(self, native_id, order, customer, lines, *, native_uuid=None):
        # The native order is durable from an earlier uncertain attempt.
        # Prove company, client, legal reference and every line BEFORE
        # adopting it. Never turn a matching POReference into authority.
        from order_to_cash.service import sales_order_fields
        if not hasattr(order, "commerce_order_id") or len(lines) != 1:
            raise IdempiereClientError("DEV11_NATIVE_ADOPTION_SCOPE_INVALID")
        fields = sales_order_fields(
            customer, order.currency, lines, reference=order.commerce_order_id)
        if native_uuid is not None:
            fields.pop("POReference")
            fields["C_Order_UU"] = native_uuid
        return self._readback(native_id, fields)

    @_observed_native_call("NATIVE_ENGINE_CREATE")
    def create_record(self, table, fields):
        if table != "C_Order" or not isinstance(fields, dict):
            raise IdempiereClientError("DEV11_NATIVE_CREATE_NOT_ALLOWED")
        reference_field = "C_Order_UU" if "C_Order_UU" in fields else "POReference"
        allowed = {"C_BPartner_ID", "CurrencyISO", "OrderLines", reference_field}
        if set(fields) != allowed or fields["CurrencyISO"] != "USD" or (
                not isinstance(fields.get(reference_field), str)
                or not _REF.fullmatch(fields[reference_field])
                or reference_field == "C_Order_UU" and not _native_uuid(fields[reference_field])):
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
        # POReference is an upstream native field, not a general canonical-ID
        # store. Bind BOTH the live application dictionary and physical width
        # before any JVM mutation; truncation would destroy retry identity.
        widths = self._sql(
            """SELECT c.fieldlength AS dictionary_width,
                      n.character_maximum_length AS database_width
               FROM adempiere.ad_column c
               JOIN adempiere.ad_table t ON t.ad_table_id=c.ad_table_id
               JOIN information_schema.columns n
                 ON n.table_schema='adempiere' AND n.table_name='c_order'
                AND n.column_name=%s
               WHERE lower(t.tablename)='c_order'
                 AND lower(c.columnname)=%s
                 AND c.isactive='Y' AND t.isactive='Y'""",
            (reference_field.lower(), reference_field.lower()))
        if len(widths) != 1:
            raise IdempiereClientError("DEV11_NATIVE_REFERENCE_METADATA_UNAVAILABLE")
        maximum = min(_positive(widths[0][key], "REFERENCE_WIDTH")
                      for key in ("dictionary_width", "database_width"))
        if len(fields[reference_field]) > maximum:
            raise IdempiereClientError("DEV11_NATIVE_REFERENCE_TOO_LONG")
        # No caller-selected product/partner is honoured by the Java fixture.
        # The Java driver asserts both IDs match its native GardenWorld seed.
        params = {
            "action": "doc", "kind": "order", "dev11_profile": "signed-event-erp",
            "org": "11", "reference": fields[reference_field],
            "reference_kind": "native-uuid" if reference_field == "C_Order_UU" else "poreference",
            "complete": "false",
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
                # The host worker and container JVM need not share a UID.
                # Match Gate D's existing readable request protocol only after
                # the complete synthetic-fixture request has been written.
                # No bearer, secret or production payload enters this bridge;
                # keep writes owner-only and publish by atomic rename below.
                os.fchmod(output.fileno(), 0o644)
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
                    # The driver outcome remains private. A known literal
                    # refusal may identify the boundary, never grant access.
                    private_error = str(data.get("error", "")) + str(data.get("driver_error", ""))
                    for code, stage in _DRIVER_REFUSALS.items():
                        if code in private_error:
                            _native_phase(stage)
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
