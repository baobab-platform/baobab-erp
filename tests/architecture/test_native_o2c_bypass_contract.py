"""Static LA-05D5 regression: every native mutation must preflight CP.
This test enforces source boundary ordering independent of synthetic runtime.
"""
import ast
import inspect
import textwrap
import unittest

from order_to_cash import service

EXPECTED = {
    "create_sales_order",
    "complete_sales_order",
    "create_shipment",
    "complete_shipment",
    "create_customer_invoice",
    "create_payment",
    "complete_payment",
    "allocate_payment",
}

class NativeMutationBoundaryTests(unittest.TestCase):
    def test_protected_mutators_gate_before_any_mapper_or_idempiere_effect(self):
        for name in sorted(EXPECTED):
            with self.subTest(action=name):
                function = getattr(service, name)
                node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
                self.assertTrue(node.body, "missing command preflight")
                first = node.body[0]
                self.assertIsInstance(first, ast.Expr)
                self.assertIsInstance(first.value, ast.Call)
                self.assertIsInstance(first.value.func, ast.Name)
                self.assertEqual(first.value.func.id, "_deny_legacy_native_action")
                self.assertIsInstance(first.value.args[1], ast.Constant)
                self.assertEqual(first.value.args[1].value, name)
                # A second operation may not borrow an invoice grant: each
                # mutator names its own exact private execution marker.

if __name__ == "__main__":
    unittest.main()
