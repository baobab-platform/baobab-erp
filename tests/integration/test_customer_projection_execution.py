"""Accepted ``trade.customer.projected`` -> business partner in the engine -> the master-data mapping orders resolve their customer through.

Real HTTP ingress (``POST /events/inbound``), real Postgres and the real worker; only iDempiere is faked, by an in-process engine that keeps
its own records and can fail on demand. What is proven is everything ERP owns: claiming, the per-customer lock, version discipline, adoption
of a partner created just before a crash, and the single transaction that records the mapping with the inbox outcome. What this does not
prove is a live iDempiere (``Description`` as the marker column, the default ``C_BP_Group`` lookup and the written fields are unconfirmed).

The acceptance tests mirror the order ones: replaying an accepted event, and restarting after an uncertain outcome, never create a second
business partner. The last test closes the loop that motivated this: an order for a customer the engine learned about only from its event.
"""
import unittest
import uuid
from unittest import mock

from integration.idempiere_client import IdempiereApiError, IdempiereClientError

from test_order_inbox_execution import CUSTOMER_PROJECTED, ORDER_PLACED, _Base, _Crash, _Engine  # noqa: F401


class PartnerEngine:
    """An in-process iDempiere for business partners. ``script`` lists how successive writes fail: 'down', 'reject', 'lose-response'."""

    def __init__(self):
        self.records, self.next, self.script, self.writes = {}, 5000, [], []
        self.groups = [{"id": 9, "C_BP_Group_ID": 9, "IsDefault": True}]

    def tables(self, table):
        return {record_id: fields for (name, record_id), fields in self.records.items() if name == table}

    def _fail(self):
        step = self.script.pop(0) if self.script else None
        if step == "down":
            raise IdempiereClientError("connection refused")
        if step == "reject":
            raise IdempiereApiError(400, "Bad Request", "customer data that must not be stored")
        return step

    def get_record(self, table, record_id):
        if (table, record_id) not in self.records:
            raise IdempiereApiError(404, "Not Found", "x")
        return self.records[(table, record_id)]

    def query(self, table, conditions, select):
        if table == "C_BP_Group":
            return list(self.groups)
        wanted = {condition.column: condition.value for condition in conditions}
        return [{f"{table}_ID": record_id} for record_id, fields in self.tables(table).items()
                if all(fields.get(column) == value for column, value in wanted.items())]

    def create_record(self, table, fields):
        step = self._fail()
        self.next += 1
        self.records[(table, self.next)] = dict(fields)
        self.writes.append(("create", self.next))
        if step == "lose-response":
            raise IdempiereClientError("connection reset after the engine acted")
        return self.next

    def update_record(self, table, record_id, fields):
        self._fail()
        self.records[(table, record_id)].update(fields)
        self.writes.append(("update", record_id))


class _Routed:
    """Business partners go to the in-process engine, everything else (orders) to the real client against the HTTP fake."""

    def __init__(self, partners, orders):
        self._partners, self._orders = partners, orders

    def _for(self, table):
        return self._partners if table in ("C_BPartner", "C_BP_Group") else self._orders

    def get_record(self, table, record_id):
        return self._for(table).get_record(table, record_id)

    def query(self, table, conditions, select):
        return self._for(table).query(table, conditions, select)

    def create_record(self, table, fields):
        return self._for(table).create_record(table, fields)

    def update_record(self, table, record_id, fields):
        return self._for(table).update_record(table, record_id, fields)


class CustomerProjectionTests(_Base):
    def setUp(self):
        super().setUp()
        self.partners = PartnerEngine()
        self.engine_present = True

    def engine_for(self, ad_client_id, ad_org_id):
        if not self.engine_present or ad_client_id != self.ad_client:
            return None
        if ad_org_id not in (0, 1):
            from order_to_cash.inbox_execution import EngineOrgMismatch
            raise EngineOrgMismatch()
        return _Routed(self.partners, super().engine_for(ad_client_id, ad_org_id))

    def projected(self, *, version=1, name="Example Importer", status="active", event_id=None, data=None, customer=None):
        customer = customer or self.customer
        body = data if data is not None else {
            "legal_entity_id": self.entity, "customer_id": customer, "customer_version": version, "customer_type": "organisation",
            "display_name": name, "status": status, "billing_country": "KE", "preferred_currency": "USD"}
        return {"specversion": "1.0", "id": event_id or str(uuid.uuid4()), "type": CUSTOMER_PROJECTED,
                "source": "urn:baobab-platform:service:trade", "subject": f"customer:{customer}", "time": "2026-10-08T09:00:00Z",
                "datacontenttype": "application/json",
                "dataschema": "https://contracts.baobab-platform.com/erp/v1/customer-projection.schema.json",
                "baobabscope": "tenant", "correlationid": str(uuid.uuid4()), "tenantid": self.tenant,
                "idempotencykey": f"trade-{customer}-v{version}", "data": body}

    def mapping(self):
        with self.db.cursor() as cursor:
            cursor.execute("SELECT native_id, desired_digest, source_version FROM baobab.erp_master_data_mapping "
                           "WHERE engine_instance_id = %s AND legal_entity_id = %s AND resource_kind = 'business_partner' "
                           "AND canonical_id = %s", (self.engine_instance, self.entity, self.customer))
            found = cursor.fetchone()
        self.db.commit()
        return found

    def seed_tenant(self):
        self.seed(customer=False, product=False)

    def partner_records(self):
        return self.partners.tables("C_BPartner")

    # -- the path ----------------------------------------------------------------------------------------------------------------
    def test_an_accepted_customer_event_becomes_a_business_partner_and_the_mapping_orders_use(self):
        self.seed_tenant()
        wire = self.projected()
        self.assertEqual(self.deliver(wire), 200)
        self.assertEqual(self.row(wire["id"])["status"], "received")  # ingress only receives

        report = self.work()

        self.assertEqual((report["pass"], report["codes"]), ({"processed": 1}, {"CREATED": 1}))
        [(native_id, fields)] = self.partner_records().items()
        self.assertEqual({k: fields[k] for k in ("Name", "Value", "IsCustomer", "IsActive", "C_BP_Group_ID")},
                         {"Name": "Example Importer", "Value": self.customer, "IsCustomer": True, "IsActive": True, "C_BP_Group_ID": 9})
        self.assertIn(self.tenant, fields["Description"])  # the marker that makes an uncertain create recoverable
        native, digest, version = self.mapping()
        self.assertEqual((native, version), (native_id, "1"))
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"], row["attempts"]), ("processed", "CREATED", 1))

    def test_a_customer_and_its_first_order_in_one_pass_the_order_no_longer_waits_for_a_hand_written_mapping(self):
        self.seed(customer=False, product=True)  # the product is mapped; the customer is known only from its event
        customer_event, order_event = self.projected(), self.placed()
        self.deliver(order_event)  # even delivered first, the customer is executed first
        self.deliver(customer_event)

        report = self.work()

        self.assertEqual(report["codes"], {"CREATED": 1, "EXECUTED": 1})
        self.assertEqual(len(self.engine_orders()), 1)
        self.assertEqual(self.engine_orders()[0]["C_BPartner_ID"], self.mapping()[0])  # the order carries the partner just created

    # -- replay, redelivery, versions ------------------------------------------------------------------------------------------------
    def test_replaying_an_accepted_event_creates_no_second_partner(self):
        self.seed_tenant()
        wire = self.projected()
        self.deliver(wire)
        self.work()
        self.deliver(wire)  # the same event id: ingress deduplicates it
        self.assertEqual(self.work()["pass"], {})
        self.assertEqual(len(self.partner_records()), 1)
        self.assertEqual(self.partners.writes, [("create", 5001)])

    def test_the_same_version_redelivered_under_a_new_event_id_is_a_no_op(self):
        self.seed_tenant()
        self.deliver(self.projected())
        self.work()
        again = self.projected()
        self.deliver(again)
        self.assertEqual(self.work()["codes"], {"ALREADY_PROJECTED": 1})
        self.assertEqual(self.partners.writes, [("create", 5001)])

    def test_a_newer_version_updates_the_partner_in_place_and_suspension_deactivates_it(self):
        self.seed_tenant()
        self.deliver(self.projected(version=1))
        self.work()
        self.deliver(self.projected(version=2, name="Renamed Importer Ltd", status="suspended"))
        self.assertEqual(self.work()["codes"], {"UPDATED": 1})
        [(native_id, fields)] = self.partner_records().items()
        self.assertEqual((fields["Name"], fields["IsActive"]), ("Renamed Importer Ltd", False))  # kept, never deleted
        self.assertEqual(self.mapping()[2], "2")
        self.assertEqual(self.partners.writes, [("create", native_id), ("update", native_id)])

    def test_an_older_version_is_ignored_and_the_same_version_with_other_content_is_refused(self):
        self.seed_tenant()
        self.deliver(self.projected(version=3))
        self.work()
        older, conflicting = self.projected(version=2, name="Older Name"), self.projected(version=3, name="Different Name")
        self.deliver(older)
        self.deliver(conflicting)
        report = self.work()
        self.assertEqual(report["codes"], {"STALE_VERSION": 1, "VERSION_CONFLICT": 1})
        self.assertEqual(self.row(conflicting["id"])["status"], "dead_letter")
        [(_, fields)] = self.partner_records().items()
        self.assertEqual(fields["Name"], "Example Importer")  # neither touched the partner
        self.assertEqual(self.partners.writes, [("create", 5001)])

    # -- an uncertain outcome is not repeated --------------------------------------------------------------------------------------------
    def test_restarting_after_an_uncertain_outcome_adopts_the_partner_instead_of_creating_another(self):
        self.seed_tenant()
        wire = self.projected()
        self.deliver(wire)
        crashed = self.connect()
        with mock.patch("customers.projection_execution.PostgresMasterDataMappingStore.put", side_effect=_Crash()):
            with self.assertRaises(_Crash):
                self.work(crashed, worker="doomed", lease=300)
        crashed.close()  # a dead process: its session lock goes with it

        self.assertEqual(len(self.partner_records()), 1)  # the engine has it, ERP does not know
        self.assertIsNone(self.mapping())
        self.assertEqual(self.work()["pass"], {})  # lease still running: nobody else may take it
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE baobab.event_inbox SET lease_expires_at = now() - interval '1 second' WHERE event_id = %s::uuid",
                           (wire["id"],))
        self.db.commit()

        self.assertEqual(self.work(worker="w2")["codes"], {"ADOPTED_NATIVE_PARTNER": 1})

        self.assertEqual(len(self.partner_records()), 1)  # still one
        self.assertEqual([w[0] for w in self.partners.writes], ["create", "update"])  # created once, then brought to this version
        self.assertEqual(self.mapping()[0], next(iter(self.partner_records())))

    def test_a_response_lost_after_the_engine_acted_is_retried_without_a_second_create(self):
        self.seed_tenant()
        wire = self.projected()
        self.deliver(wire)
        self.partners.script = ["lose-response"]
        self.assertEqual(self.work()["codes"], {"ENGINE_UNAVAILABLE": 1})
        self.assertEqual(len(self.partner_records()), 1)
        self.make_due(wire["id"])
        self.assertEqual(self.work()["codes"], {"ADOPTED_NATIVE_PARTNER": 1})
        self.assertEqual(len(self.partner_records()), 1)

    def test_an_event_for_a_customer_another_worker_is_on_is_contended_not_failed(self):
        self.seed_tenant()
        wire = self.projected()
        self.deliver(wire)
        holder = self.connect()
        key = f"baobab.customer|{self.tenant}|{self.entity}|{self.customer}"
        with holder.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (key,))
        self.assertEqual(self.work()["codes"], {"CUSTOMER_CONTENDED": 1})
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["attempts"]), ("retry", 0))  # the claim was refunded
        self.assertEqual(self.partner_records(), {})

    # -- what is not started ------------------------------------------------------------------------------------------------------------
    def _blocked(self, code):
        wire = self.projected()
        self.deliver(wire)
        self.assertEqual(self.work()["codes"], {code: 1})
        row = self.row(wire["id"])
        self.assertEqual((row["status"], row["code"]), ("blocked", code))
        self.assertEqual(self.partner_records(), {})  # nothing was created or invented
        self.assertIsNone(self.mapping())

    def test_a_tenant_with_no_engine_placement_blocks_the_event(self):
        self._blocked("TENANT_UNMAPPED")

    def test_a_tenant_whose_client_has_no_engine_credentials_blocks_the_event(self):
        self.seed_tenant()
        self.engine_present = False
        self._blocked("ENGINE_UNCONFIGURED")

    def test_credentials_for_another_org_than_the_tenants_block_the_event(self):
        with self.db.cursor() as cursor:
            cursor.execute("INSERT INTO baobab.tenant_mapping (tenant_id, entity_id, ad_client_id, ad_org_id, legal_entity_id, "
                           "engine_instance_id) VALUES (%s,%s,%s,7,%s,%s)",
                           (self.tenant, self.entity, self.ad_client, self.entity, self.engine_instance))
        self.db.commit()
        self._blocked("ENGINE_ORG_MISMATCH")

    def test_a_client_without_exactly_one_default_partner_group_blocks_the_event(self):
        for groups in ([], [{"id": 1, "IsDefault": True}, {"id": 2, "IsDefault": True}]):
            self.partners.groups = groups
            self.seed_tenant() if not self.scalar("SELECT count(*) FROM baobab.tenant_mapping WHERE tenant_id = %s", self.tenant) else None
            wire = self.projected(version=1 + len(groups))
            self.deliver(wire)
            self.assertEqual(self.work()["codes"], {"BP_GROUP_UNAVAILABLE": 1})
            self.assertEqual(self.row(wire["id"])["status"], "blocked")
        self.assertEqual(self.partner_records(), {})

    def test_a_malformed_payload_is_a_dead_letter_and_the_engine_is_never_called(self):
        self.seed_tenant()
        for name, data in (("no version", {"legal_entity_id": self.entity, "customer_id": self.customer, "customer_type": "person",
                                           "display_name": "x", "status": "active"}),
                           ("unknown status", {"legal_entity_id": self.entity, "customer_id": self.customer, "customer_version": 1,
                                               "customer_type": "person", "display_name": "x", "status": "deleted"})):
            with self.subTest(name):
                wire = self.projected(data=data)
                try:
                    self.deliver(wire)
                except Exception:  # noqa: BLE001
                    continue  # ingress already refused it against the schema
                self.work()
                self.assertEqual(self.row(wire["id"])["code"], "PAYLOAD_INVALID")
        self.assertEqual(self.partners.writes, [])

    # -- engine trouble -----------------------------------------------------------------------------------------------------------------
    def test_an_engine_that_is_down_is_retried_and_one_that_refuses_is_a_dead_letter_without_its_message(self):
        self.seed_tenant()
        wire = self.projected()
        self.deliver(wire)
        self.partners.script = ["down"]
        self.assertEqual(self.work()["codes"], {"ENGINE_UNAVAILABLE": 1})
        self.assertEqual(self.row(wire["id"])["status"], "retry")
        self.partners.script = ["reject"]
        self.make_due(wire["id"])
        self.assertEqual(self.work()["codes"], {"ENGINE_REJECTED": 1})
        row = self.row(wire["id"])
        self.assertEqual(row["status"], "dead_letter")
        self.assertNotIn("customer data", row["error"] or "")

    def test_two_partners_carrying_one_marker_are_left_to_an_operator(self):
        from customers.payload import marker, parse_customer_projected

        self.seed_tenant()
        wire = self.projected()
        text = marker(self.tenant, parse_customer_projected(wire["data"]))
        self.partners.create_record("C_BPartner", {"Description": text})
        self.partners.create_record("C_BPartner", {"Description": text})
        self.deliver(wire)
        self.assertEqual(self.work()["codes"], {"DUPLICATE_NATIVE_PARTNERS": 1})
        self.assertEqual(len(self.partner_records()), 2)

    def test_a_mapped_partner_that_has_vanished_from_the_engine_is_a_dead_letter(self):
        self.seed_tenant()
        self.deliver(self.projected(version=1))
        self.work()
        self.partners.records.clear()  # someone deleted it in the engine
        self.deliver(self.projected(version=2, name="Renamed"))
        self.assertEqual(self.work()["codes"], {"NATIVE_PARTNER_MISSING": 1})


if __name__ == "__main__":
    unittest.main()
