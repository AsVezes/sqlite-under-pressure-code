"""L30/C28 black-box regression: run the published reader entry point in both modes.

The lab itself owns disposable fixtures. This test verifies the public JSON
contract, negative controls, and that -O does not disable safety checks.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

LAB = Path(__file__).with_name("l30_transfer_drill.py")


class L30TransferRegression(unittest.TestCase):
    def test_normal_and_optimized_entry_points(self):
        results = []
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable]
                if optimized:
                    command.append("-O")
                command.append(str(LAB))
                completed = subprocess.run(
                    command, capture_output=True, text=True, timeout=40,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode, 0,
                    f"{command!r}\nstdout={completed.stdout}\nstderr={completed.stderr}",
                )
                self.assertEqual(completed.stderr, "")
                payload = json.loads(completed.stdout)
                self.assertEqual(payload["lab"], "L30")
                self.assertEqual(payload["chapter"], "C28")
                self.assertEqual(payload["oracle"], "PASS")
                self.assertEqual(payload["backup_cut"], 5)
                self.assertEqual(payload["last_acknowledged"], 6)
                self.assertEqual(payload["rpo_operations_observed"], 1)
                self.assertEqual(payload["final_receipts"], 6)
                self.assertIs(payload["negative_zero_loss_claim_rejected"], True)
                self.assertIs(payload["negative_conflicting_receipt_rejected"], True)
                self.assertEqual(len(payload["backup_sha256"]), 64)
                self.assertTrue(payload["engine"]["version"])
                self.assertTrue(payload["engine"]["source_id"])
                self.assertGreaterEqual(
                    payload["restore_and_reconcile_ms_observed"], 0,
                )
                results.append(payload)
        self.assertEqual(results[0]["engine"], results[1]["engine"])


if __name__ == "__main__":
    unittest.main()
