#!/usr/bin/env python3
"""L11 regression: python3 -m unittest discover -s labs -p 'test_l11_*.py' -v."""
import unittest
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


if __name__ == "__main__":
    unittest.main()
