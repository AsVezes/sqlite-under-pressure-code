"""Regression checks for the disposable L12 probe."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import l12_busy_locked


class L12Tests(unittest.TestCase):
    def test_oracles_and_order(self):
        report = l12_busy_locked.run()
        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(all(v is True for v in report["oracles"].values()))
        self.assertLess(report["events"].index("B_READ_LOCK_ACK"),
                        report["events"].index("A_COMMIT_BUSY_ACK"))
        self.assertLess(report["events"].index("B_READ_RELEASED_ACK"),
                        report["events"].index("A_COMMIT_RETRY_SUCCEEDED_ACK"))
        self.assertTrue(report["environment"]["sqlite_source_id"])

    def test_cli_rejects_paths(self):
        script = Path(l12_busy_locked.__file__)
        result = subprocess.run([sys.executable, str(script), "/tmp/external.db"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("No arguments", result.stderr)

    def test_json_cli(self):
        script = Path(l12_busy_locked.__file__)
        result = subprocess.run([sys.executable, str(script)], capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
