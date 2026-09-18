import os
import unittest


class ZuribeansRelease1GoldenTests(unittest.TestCase):
    """Exercises complete Zuribeans_ZA/Zuribeans_UG business flows end-to-end against a
    real provisioned iDempiere instance, per tests/golden/README.md and this gate's
    activation runbook. Golden evidence for ActivationEvaluator must come from a real
    run against real infrastructure -- never a mock standing in for one -- so this
    always skips rather than fabricating a passing result.
    """

    def setUp(self):
        if os.environ.get("RUN_IDEMPIERE_GOLDEN") != "1":
            raise unittest.SkipTest(
                "RUN_IDEMPIERE_GOLDEN != 1; requires a provisioned test iDempiere and "
                "Baobab integration stack, never mocked (see tests/golden/README.md)"
            )
        raise unittest.SkipTest(
            "RUN_IDEMPIERE_GOLDEN=1 but no concrete TradeGoldenClient/ErpGoldenClient/"
            "ReconciliationClient wiring exists yet -- this environment cannot provision "
            "or reach a live iDempiere instance to build that wiring against"
        )

    def test_za_and_ug_are_executed_as_distinct_legal_entities(self):
        self.fail("unreachable: setUp always skips until real golden client wiring exists")

    def test_reverse_market_capability_is_not_hard_coded(self):
        self.fail("unreachable: setUp always skips until real golden client wiring exists")


if __name__ == "__main__":
    unittest.main()
