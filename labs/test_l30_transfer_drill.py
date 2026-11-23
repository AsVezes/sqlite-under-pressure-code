"""L30/C28 black-box regression: run the published reader entry point in both modes.

The lab itself owns disposable fixtures. This test verifies the public JSON
contract, negative controls, and that -O does not disable safety checks.
"""
import json
import sqlite3
import tempfile
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


    def test_restore_gate_rejects_semantic_and_receipt_corruption(self):
        # Exercise the published gate directly, not a reimplementation.
        import importlib.util
        spec = importlib.util.spec_from_file_location("l30_transfer_drill", LAB)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="l30-negative-") as root:
            db_path = Path(root) / "disposable.sqlite"
            with sqlite3.connect(db_path) as db:
                db.executescript(
                    "CREATE TABLE receipts(op_id INTEGER PRIMARY KEY, delta INTEGER NOT NULL);"
                    "CREATE TABLE balance(amount INTEGER NOT NULL);"
                    "INSERT INTO receipts VALUES(1,1);"
                    "INSERT INTO balance VALUES(1);"
                )
            self.assertEqual(module.check(db_path, [(1, 1)]), [(1, 1)])
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE balance SET amount=99")
            with self.assertRaisesRegex(RuntimeError, "balance invariant failed"):
                module.check(db_path, [(1, 1)])
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE balance SET amount=1")
                db.execute("UPDATE receipts SET delta=2 WHERE op_id=1")
            with self.assertRaisesRegex(RuntimeError, "receipt continuity mismatch"):
                module.check(db_path, [(1, 1)])

    def test_optimized_restore_gate_remains_active(self):
        # The two adversarial gates must also run with assertions disabled.
        script = """
import importlib.util, sqlite3, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("l30", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as root:
    p = Path(root) / "scratch.sqlite"
    with sqlite3.connect(p) as db:
        db.executescript("CREATE TABLE receipts(op_id INTEGER PRIMARY KEY, delta INTEGER);"
                         "CREATE TABLE balance(amount INTEGER);"
                         "INSERT INTO receipts VALUES(1,1);"
                         "INSERT INTO balance VALUES(99);")
    try:
        m.check(p, [(1,1)])
    except RuntimeError as exc:
        if str(exc) != "balance invariant failed":
            raise
    else:
        raise RuntimeError("optimized mode bypassed balance gate")
print("negative_balance_gate=PASS")
"""
        completed = subprocess.run(
            [sys.executable, "-O", "-c", script, str(LAB)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(
            completed.returncode, 0,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        self.assertEqual(completed.stdout.strip(), "negative_balance_gate=PASS")
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
