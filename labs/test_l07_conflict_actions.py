"""Regression controls for the L07 conflict-action pilot (disposable files only).

Run: python3 -m unittest discover -s labs -p 'test_l07_*.py' -v
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import l07_conflict_actions as lab


ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "ABORT": [[1, 10], [2, 20], [3, 30]],
    "FAIL": [[1, 10], [2, 20], [3, 30], [4, 40]],
    "IGNORE": [[1, 10], [2, 20], [3, 30], [4, 40], [6, 60]],
    "ROLLBACK": [[1, 10], [2, 20]],
}


class ConflictActionsTests(unittest.TestCase):
    def test_each_action_has_distinct_persisted_outcome(self):
        report = lab.run()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["lab"], "L07")
        self.assertTrue(report["environment"]["sqlite_source_id"])
        self.assertTrue(report["environment"]["sqlite_version"])
        self.assertEqual(len(report["cases"]), 4)
        for case in report["cases"]:
            with self.subTest(action=case["algorithm"]):
                action = case["algorithm"]
                self.assertEqual(case["before_reopen"], EXPECTED[action])
                self.assertEqual(case["after_reopen"], EXPECTED[action])
                self.assertTrue(all(value is True for value in case["oracles"].values()))
                self.assertEqual(case["transaction_active_after_statement"], action != "ROLLBACK")
                if action == "IGNORE":
                    self.assertIsNone(case["error"])
                else:
                    self.assertEqual(case["error"]["code"], lab.sqlite3.SQLITE_CONSTRAINT_UNIQUE)

    def test_negative_control_oracle_rejects_wrong_persisted_state(self):
        # An integrity_check of 'ok' alone must never accept an incorrect
        # business result. Exercise the same explicit fail-closed guard.
        wrong = [[1, 10], [2, 20], [3, 30], [4, 40]]
        with self.assertRaisesRegex(RuntimeError, "L07 oracle failed: persisted_state"):
            lab.require(wrong == EXPECTED["ABORT"], "persisted_state")

    def test_optimized_python_keeps_checks_and_json(self):
        command = [sys.executable, "-O", str(ROOT / "l07_conflict_actions.py")]
        completed = subprocess.run(command, capture_output=True, text=True,
                                   check=False, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "pass")
        self.assertEqual({c["algorithm"] for c in report["cases"]}, set(EXPECTED))
        self.assertTrue(all(all(c["oracles"].values()) for c in report["cases"]))


if __name__ == "__main__":
    unittest.main()
