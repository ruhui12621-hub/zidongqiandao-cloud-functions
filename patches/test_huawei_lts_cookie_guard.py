import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, "runtime")
import huawei_lts_cookie_guard as guard


class CookieGuardTests(unittest.TestCase):
    def setUp(self):
        self.context = object()
        self.credential = "ltuid=123; ltoken=secret"

    def test_fingerprint_is_sha256_and_does_not_expose_credential(self):
        value = guard.fingerprint(self.credential)
        self.assertEqual(len(value), 64)
        self.assertNotIn("secret", value)

    def test_hoyolab_cookie_fingerprint_ignores_order_and_spacing(self):
        first = guard.fingerprint("ltuid=123; ltoken=abc; mid=xyz", "hoyolab")
        second = guard.fingerprint(" mid=xyz ;ltoken=abc;ltuid=123 ", "hoyolab")
        self.assertEqual(first, second)

    def test_latest_invalid_report_blocks_and_emits_timestamped_renewal(self):
        previous = {"status": "INVALID", "timestamp": "2026-11-27T10:00:00Z"}
        output = io.StringIO()
        with patch.object(guard, "_query_recent_report", return_value=previous):
            with redirect_stdout(output):
                self.assertTrue(guard.should_skip(self.context, "hoyolab", "acct-1", self.credential))
        self.assertIn("[COOKIE_STATUS_JSON]=", output.getvalue())
        self.assertIn('"status":"INVALID"', output.getvalue())
        self.assertIn('"timestamp":', output.getvalue())
        self.assertIn('"account_id":"acct-1"', output.getvalue())

    def test_latest_valid_report_overrides_older_invalid_report(self):
        previous = {"status": "VALID", "timestamp": "2026-11-27T10:00:00Z"}
        with patch.object(guard, "_query_recent_report", return_value=previous):
            self.assertFalse(guard.should_skip(self.context, "hoyolab", "acct-1", self.credential))

    def test_no_report_allows_request(self):
        with patch.object(guard, "_query_recent_report", return_value=None):
            self.assertFalse(guard.should_skip(self.context, "skland", "acct-2", self.credential))

    def test_query_failure_fails_open_and_logs_reason(self):
        output = io.StringIO()
        with patch.object(guard, "_query_recent_report", side_effect=RuntimeError("no IAM token")):
            with redirect_stdout(output):
                self.assertFalse(guard.should_skip(self.context, "skland", "acct-2", self.credential))
        self.assertIn("QUERY_UNAVAILABLE", output.getvalue())

    def test_report_parser_reads_embedded_json(self):
        record = guard.report("hoyolab", "acct-1", self.credential, "VALID", "test")
        parsed = guard._parse_report("2026-11-27 INFO " + guard.REPORT_PREFIX +
                                     __import__("json").dumps(record))
        self.assertEqual(parsed["sha256"], guard.fingerprint(self.credential, "hoyolab"))
        self.assertEqual(parsed["status"], "VALID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
