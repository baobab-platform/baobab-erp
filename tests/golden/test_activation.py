import unittest

from provisioning.activation import ActivationEvaluator, ActivationEvidenceError, Evidence, GateStatus


def all_evidence(**overrides):
    items = {name: Evidence(name, GateStatus.PASS, "ref") for name in ActivationEvaluator.REQUIRED}
    items.update(overrides)
    return list(items.values())


class ActivationEvaluatorTests(unittest.TestCase):
    def test_missing_golden_path_blocks_activation(self):
        evidence = [e for e in all_evidence() if e.check != "fx_golden"]

        report = ActivationEvaluator().evaluate("le-za", evidence)

        self.assertFalse(report.ready)
        self.assertTrue(any("fx_golden" in b for b in report.blockers))

    def test_all_evidence_allows_ready(self):
        report = ActivationEvaluator().evaluate("le-ug", all_evidence())

        self.assertTrue(report.ready)
        self.assertEqual(report.blockers, ())

    def test_a_failed_gate_blocks_activation_with_its_reason(self):
        evidence = all_evidence(reconciliation=Evidence("reconciliation", GateStatus.FAIL, "ref", reason="AP/AR out of balance"))

        report = ActivationEvaluator().evaluate("le-za", evidence)

        self.assertFalse(report.ready)
        self.assertIn("reconciliation: AP/AR out of balance", report.blockers)

    def test_passing_gate_requires_a_non_empty_reference(self):
        with self.assertRaises(ActivationEvidenceError):
            Evidence("sales_golden", GateStatus.PASS, "")

    def test_duplicate_evidence_for_the_same_gate_is_rejected(self):
        evidence = [
            Evidence("sales_golden", GateStatus.PASS, "ref-1"),
            Evidence("sales_golden", GateStatus.FAIL, "ref-2"),
        ]
        with self.assertRaises(ActivationEvidenceError):
            ActivationEvaluator().evaluate("le-za", evidence)

    def test_independent_activation_across_legal_entities(self):
        za_report = ActivationEvaluator().evaluate("le-za", all_evidence())
        ug_evidence = [e for e in all_evidence() if e.check != "fx_golden"]
        ug_report = ActivationEvaluator().evaluate("le-ug", ug_evidence)

        self.assertTrue(za_report.ready)
        self.assertFalse(ug_report.ready)


if __name__ == "__main__":
    unittest.main()
