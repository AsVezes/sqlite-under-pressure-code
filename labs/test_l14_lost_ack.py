"""Adversarial L14 regression tests (all database paths are disposable)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from l14_lost_ack import require, run, setup, snapshot, transfer


class LostAckTests(unittest.TestCase):
    def test_end_to_end(self):
        # Includes a child process, explicit commit ACK and rollback-before-commit.
        run()

    def test_replay_is_not_a_second_transfer(self):
        with tempfile.TemporaryDirectory(prefix="l14-regression-") as root:
            db = setup(Path(root) / "receipt.sqlite3")
            try:
                self.assertEqual(transfer(db, "op-1", 3), "applied")
                first = snapshot(db)
                self.assertEqual(transfer(db, "op-1", 3), "replayed")
                self.assertEqual(snapshot(db), first)
                with self.assertRaisesRegex(RuntimeError, "IDEMPOTENCY_CONFLICT"):
                    transfer(db, "op-1", 4)
                self.assertEqual(snapshot(db), first)
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                db.close()

    def test_negative_without_deduplication(self):
        # Deliberately broken application variant: repeats the movement without
        # consulting or writing the receipt. Demonstrates that stock conservation
        # alone cannot detect duplicate business operations.
        with tempfile.TemporaryDirectory(prefix="l14-negative-") as root:
            db = setup(Path(root) / "negative.sqlite3")
            try:
                self.assertEqual(transfer(db, "op-1", 3), "applied")
                expected = snapshot(db)
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE stock SET qty=qty-3 WHERE location='A'")
                db.execute("UPDATE stock SET qty=qty+3 WHERE location='B'")
                db.execute("COMMIT")
                actual = snapshot(db)
                self.assertEqual(actual["receipts"], expected["receipts"])
                self.assertEqual(sum(qty for _, qty in actual["stock"]), 10)
                with self.assertRaisesRegex(RuntimeError, "DUPLICATE_EFFECT_DETECTED"):
                    require(actual["stock"] == expected["stock"],
                            "DUPLICATE_EFFECT_DETECTED")
                self.assertEqual(actual["stock"], [("A", 4), ("B", 6)])
            finally:
                db.close()

    def test_negative_oracle_survives_optimized_python(self):
        with self.assertRaisesRegex(RuntimeError, "ORACLE_FALSE"):
            require(False, "ORACLE_FALSE")


if __name__ == "__main__":
    unittest.main()
