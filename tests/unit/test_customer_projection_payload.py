"""The rules for reading a ``customer.projected`` payload: strict where the contract is, silent about what ERP does not store.
No database; the Postgres behaviour is tests/integration/test_customer_projection_execution.py."""
import unittest

from customers.payload import CustomerProjection, PayloadError, marker, parse_customer_projected


def valid(**overrides):
    data = {"legal_entity_id": "ZURIBEANS", "customer_id": "customer_01k4n6x2", "customer_version": 4, "customer_type": "organisation",
            "display_name": "Example Importer", "status": "active", "billing_country": "KE", "preferred_currency": "USD"}
    data.update(overrides)
    return data


class ParseTests(unittest.TestCase):
    def test_the_shared_example_parses(self):
        parsed = parse_customer_projected(valid())
        self.assertEqual((parsed.customer_id, parsed.customer_version, parsed.display_name, parsed.active),
                         ("customer_01k4n6x2", 4, "Example Importer", True))

    def test_optional_members_may_be_absent_and_unknown_ones_are_ignored(self):
        data = valid(tax_registration_references=["tax_ref_001"], extra="ignored")
        del data["billing_country"], data["preferred_currency"]
        self.assertEqual(parse_customer_projected(data).display_name, "Example Importer")

    def test_a_malformed_member_is_refused_with_a_fixed_reason(self):
        bad = {
            "not an object": None,
            "no customer id": valid(customer_id=None),
            "short customer id": valid(customer_id="ab"),
            "customer id with a space": valid(customer_id="customer one"),
            "zero version": valid(customer_version=0),
            "boolean version": valid(customer_version=True),
            "string version": valid(customer_version="4"),
            "unknown type": valid(customer_type="company"),
            "blank name": valid(display_name="   "),
            "control character in name": valid(display_name="Acme\nLtd"),
            "name over 255": valid(display_name="x" * 256),
            "unknown status": valid(status="deleted"),
            "bad country": valid(billing_country="Kenya"),
            "bad currency": valid(preferred_currency="usd"),
            "no legal entity": valid(legal_entity_id=None),
        }
        for name, data in bad.items():
            with self.subTest(name):
                with self.assertRaises(PayloadError) as caught:
                    parse_customer_projected(data)
                self.assertNotIn("Acme", str(caught.exception))  # a reason never repeats payload content

    def test_only_an_active_customer_is_an_active_partner(self):
        self.assertEqual([parse_customer_projected(valid(status=s)).active for s in ("active", "suspended", "closed")],
                         [True, False, False])


class DigestTests(unittest.TestCase):
    def test_the_digest_follows_content_and_not_the_version(self):
        base = parse_customer_projected(valid())
        self.assertEqual(base.digest(), parse_customer_projected(valid(customer_version=9)).digest())
        for change in ({"display_name": "Other"}, {"status": "suspended"}, {"customer_type": "person"}):
            with self.subTest(change):
                self.assertNotEqual(base.digest(), parse_customer_projected(valid(**change)).digest())

    def test_the_name_is_trimmed_so_padding_is_not_a_change(self):
        self.assertEqual(parse_customer_projected(valid(display_name="  Example Importer ")).digest(),
                         parse_customer_projected(valid()).digest())


class MarkerTests(unittest.TestCase):
    def test_a_marker_is_unique_to_tenant_legal_entity_and_customer(self):
        customer = CustomerProjection("ZURIBEANS", "customer_001", 1, "person", "A", "active")
        markers = {marker("tn_a", customer), marker("tn_b", customer),
                   marker("tn_a", CustomerProjection("OTHERENTITY", "customer_001", 1, "person", "A", "active")),
                   marker("tn_a", CustomerProjection("ZURIBEANS", "customer_002", 1, "person", "A", "active"))}
        self.assertEqual(len(markers), 4)  # two tenants' same customer id can never adopt each other's partner


if __name__ == "__main__":
    unittest.main()
