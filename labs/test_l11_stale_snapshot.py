#!/usr/bin/env python3
"""L11 regression: python3 -m unittest discover -s labs -p 'test_l11_*.py' -v."""
import unittest
from unittest.mock import patch
import l11_stale_snapshot as lab


class L11Tests(unittest.TestCase):
    def test_snapshot_promotion_and_control(self):
        report = lab.run()
        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(all(report["oracles"].values()), report)
        self.assertTrue(report["environment"]["sqlite_source_id"])

    def test_explicit_phase_order(self):
        report = lab.run()
        self.assertEqual(
            [event["phase"] for event in report["events"]],
            ["A_READ_ACK", "B_COMMIT_ACK", "A_PROMOTION_ACK",
             "A_ROLLBACK_ACK", "A_FRESH_COMMIT_ACK", "B_CONTROL_COMMIT_ACK"],
        )
        self.assertEqual(report["events"][2]["error"]["code"], 517)
        self.assertEqual(report["observations"]["control_final"], 4)

    def test_error_name_and_primary_code(self):
        report = lab.run()
        error = report["events"][2]["error"]
        self.assertEqual(error["name"], "SQLITE_BUSY_SNAPSHOT")
        self.assertEqual(error["code"] & 255, lab.sqlite3.SQLITE_BUSY)
        self.assertEqual(report["observations"]["old_view"], 0)
        self.assertEqual(report["observations"]["fresh_view"], 1)

    def test_negative_control_wrong_extended_code_fails_closed(self):
        # Force an incorrect expected code; the lab must report failure even under -O.
        with patch.object(lab.sqlite3, "SQLITE_BUSY_SNAPSHOT", 999, create=True):
            report = lab.run()
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["oracles"]["extended_busy_snapshot"])
        self.assertTrue(all(value for key, value in report["oracles"].items()
                            if key != "extended_busy_snapshot"))


if __name__ == "__main__":
    unittest.main()
