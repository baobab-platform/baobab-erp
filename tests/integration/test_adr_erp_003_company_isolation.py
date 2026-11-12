"""ADR-ERP-003/021: native Client is the hard company boundary.

Real PostgreSQL 17 constraint proof; does not pretend that the Control Plane
or a standalone EngineInstance was independently qualified by this test.
"""
from __future__ import annotations

import uuid
import unittest

import psycopg

from _postgres import connect


class DedicatedClientIsolationTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect()
        self.tenant = "tn_" + uuid.uuid4().hex[:16]
        self.instance = "ei_" + uuid.uuid4().hex[:16]
        self.other_instance = "ei_" + uuid.uuid4().hex[:16]
        self.native_client = int(uuid.uuid4().hex[:7], 16) + 500000
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.connection.rollback()
        with self.connection.cursor() as cur:
            cur.execute("DELETE FROM baobab.tenant_mapping WHERE tenant_id = %s", (self.tenant,))
        self.connection.commit()
        self.connection.close()

    def _insert(self, entity, client, org, instance):
        with self.connection.cursor() as cur:
            cur.execute(
                """INSERT INTO baobab.tenant_mapping
                    (tenant_id, entity_id, legal_entity_id, ad_client_id, ad_org_id, engine_instance_id)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (self.tenant, entity, entity, client, org, instance),
            )

    def test_second_legal_entity_cannot_share_client_by_switching_org(self):
        self._insert("ZB-ZA", self.native_client, 100, self.instance)
        self.connection.commit()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._insert("ZB-UG", self.native_client, 101, self.instance)
        self.connection.rollback()
        with self.connection.cursor() as cur:
            cur.execute(
                """SELECT entity_id, ad_client_id, ad_org_id
                   FROM baobab.tenant_mapping
                   WHERE tenant_id=%s AND engine_instance_id=%s""",
                (self.tenant, self.instance),
            )
            self.assertEqual(cur.fetchall(), [("ZB-ZA", self.native_client, 100)])

    def test_two_separate_clients_can_be_placed_on_one_engine_instance(self):
        self._insert("ZB-ZA", self.native_client, 100, self.instance)
        self._insert("ZB-UG", self.native_client + 1, 101, self.instance)
        with self.connection.cursor() as cur:
            cur.execute(
                """SELECT count(DISTINCT ad_client_id) FROM baobab.tenant_mapping
                   WHERE tenant_id=%s AND engine_instance_id=%s""",
                (self.tenant, self.instance),
            )
            self.assertEqual(cur.fetchone()[0], 2)

    def test_identical_native_client_number_in_distinct_instances_is_not_a_canonical_identity(self):
        # Existing legacy unique native (Client, Org) still needs explicit
        # EngineInstance scoping in the reverse API; use different orgs here.
        self._insert("ZB-ZA", self.native_client, 100, self.instance)
        self._insert("OTHER-ZA", self.native_client, 101, self.other_instance)
        with self.connection.cursor() as cur:
            cur.execute(
                """SELECT count(DISTINCT engine_instance_id) FROM baobab.tenant_mapping
                   WHERE tenant_id=%s AND ad_client_id=%s""",
                (self.tenant, self.native_client),
            )
            self.assertEqual(cur.fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
