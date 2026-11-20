#!/usr/bin/env python3
"""L10 regression: python3 -m unittest discover -s labs -p 'test_l10_*.py' -v."""
import sqlite3
import unittest
import l10_writer_busy as lab


class L10WriterBusyTests(unittest.TestCase):
    def test_busy_then_explicit_retry(self):
        report = lab.run()
        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(all(report["oracles"].values()), report)
        self.assertEqual(report["observations"]["after_a_commit"], 1)
        self.assertEqual(report["observations"]["final_counter"], 2)
        self.assertTrue(report["environment"]["sqlite_source_id"])

    def test_busy_is_not_stale_snapshot(self):
        report = lab.run()
        phases = [event["phase"] for event in report["events"]]
        self.assertEqual(phases, [
            "A_WRITE_ACK", "B_BUSY_ACK", "A_COMMIT_ACK", "B_RETRY_COMMIT_ACK"
        ])
        self.assertEqual(report["events"][1]["error"]["code"], sqlite3.SQLITE_BUSY)
        self.assertFalse(report["observations"]["b_in_transaction_after_busy"])


if __name__ == "__main__":
    unittest.main()
