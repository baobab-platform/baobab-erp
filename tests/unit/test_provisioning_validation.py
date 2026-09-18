import unittest
from dataclasses import replace
from datetime import datetime, timezone

from provisioning.model import PENDING_DATE, PENDING_DATETIME
from provisioning.validation import validate_request
from test_provisioning_planner import valid_request


class ProvisioningValidationTests(unittest.TestCase):
    def test_fully_configured_request_has_no_pending_date_checks(self):
        checks = {c.code: c.ready for c in validate_request(valid_request())}
        self.assertTrue(checks["effective_date"])
        self.assertTrue(checks["accounting.approved_at"])

    def test_pending_effective_date_fails_closed(self):
        request = replace(valid_request(), effective_date=PENDING_DATE)
        checks = {c.code: c.ready for c in validate_request(request)}
        self.assertFalse(checks["effective_date"])

    def test_pending_approved_at_fails_closed(self):
        pending_accounting = replace(valid_request().accounting, approved_at=PENDING_DATETIME)
        request = replace(valid_request(), accounting=pending_accounting)
        checks = {c.code: c.ready for c in validate_request(request)}
        self.assertFalse(checks["accounting.approved_at"])

    def test_a_real_but_early_datetime_is_not_confused_with_pending(self):
        # PENDING_DATETIME is datetime.min; make sure the check is an actual
        # sentinel comparison, not "any old/unlikely-looking date fails".
        real_but_old = replace(valid_request().accounting, approved_at=datetime(1999, 1, 1, tzinfo=timezone.utc))
        request = replace(valid_request(), accounting=real_but_old)
        checks = {c.code: c.ready for c in validate_request(request)}
        self.assertTrue(checks["accounting.approved_at"])


if __name__ == "__main__":
    unittest.main()
