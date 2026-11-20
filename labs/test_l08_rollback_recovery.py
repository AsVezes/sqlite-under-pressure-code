"""Regression tests for L08's disposable rollback-journal recovery pilot.

Run: python3 -m unittest discover -s labs -p 'test_l08_*.py' -v
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROBE = Path(__file__).with_name("l08_rollback_recovery.py")


class L08RecoveryTests(unittest.TestCase):
    def test_worker_interruption_restores_committed_value(self):
        result = subprocess.run(
            [sys.executable, str(PROBE)],
            capture_output=True, text=True, timeout=35, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["lab"], "L08")
        self.assertEqual(evidence["status"], "pass")
        self.assertTrue(evidence["sqlite_version"])
        self.assertTrue(evidence["sqlite_source_id"])
        self.assertTrue(evidence["python"])
        self.assertTrue(evidence["platform"])
        self.assertEqual(evidence["inputs"]["journal_mode"], "DELETE")
        self.assertEqual(evidence["observed"]["qty_after_reopen"], 10)
        self.assertEqual(evidence["observed"]["integrity_check"], "ok")
        self.assertEqual(
            set(evidence["oracles"]),
            {
                "ready_after_uncommitted_update",
                "journal_during_transaction",
                "journal_after_termination",
                "original_value_after_reopen",
                "integrity_check_ok",
            },
        )
        self.assertTrue(all(type(value) is bool and value for value in evidence["oracles"].values()))

    def test_external_path_is_rejected_before_probe(self):
        result = subprocess.run(
            [sys.executable, str(PROBE), "/nonexistent/never-use.sqlite3"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertEqual(result.stdout, "")
        self.assertIn("accepts no arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
