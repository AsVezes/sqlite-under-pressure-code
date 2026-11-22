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

    def test_failed_business_operations_leave_no_receipt_or_debit(self):
        # A rejected request must not reserve its idempotency key or change stock.
        with tempfile.TemporaryDirectory(prefix="l14-rejected-") as root:
            db = setup(Path(root) / "rejected.sqlite3")
            try:
                initial = snapshot(db)
                for key, amount, reason in (
                    ("invalid", 0, "INVALID_AMOUNT"),
                    ("insufficient", 11, "INSUFFICIENT_STOCK"),
                ):
                    with self.subTest(reason=reason):
                        with self.assertRaisesRegex(RuntimeError, reason):
                            transfer(db, key, amount)
                        self.assertFalse(db.in_transaction)
                        self.assertEqual(snapshot(db), initial)
                # A failed request with this key did not consume the receipt.
                self.assertEqual(transfer(db, "insufficient", 3), "applied")
                self.assertEqual(snapshot(db), {
                    "stock": [("A", 7), ("B", 3)],
                    "receipts": [("insufficient", 3)],
                })
            finally:
                db.close()

    def test_invalid_idempotency_keys_fail_closed(self):
        # SQLite rowid tables may permit multiple NULLs in TEXT PRIMARY KEY.
        # The API and schema must reject NULL, blank and whitespace-only keys.
        with tempfile.TemporaryDirectory(prefix="l14-key-negative-") as root:
            db = setup(Path(root) / "invalid-key.sqlite3")
            try:
                baseline = snapshot(db)
                for key in (None, "", "   ", 42):
                    with self.subTest(key=key):
                        with self.assertRaisesRegex(RuntimeError, "INVALID_IDEMPOTENCY_KEY"):
                            transfer(db, key, 3)
                        self.assertFalse(db.in_transaction)
                        self.assertEqual(snapshot(db), baseline)
                for key in (None, "", "   "):
                    with self.subTest(schema_key=key):
                        with self.assertRaises(sqlite3.IntegrityError):
                            db.execute("INSERT INTO receipts(id,amount) VALUES (?,3)", (key,))
                        self.assertEqual(snapshot(db), baseline)
                self.assertEqual(transfer(db, "valid-key", 3), "applied")
                self.assertEqual(transfer(db, "valid-key", 3), "replayed")
                self.assertEqual(snapshot(db)["stock"], [("A", 7), ("B", 3)])
            finally:
                db.close()

    def test_negative_oracle_survives_optimized_python(self):
        with self.assertRaisesRegex(RuntimeError, "ORACLE_FALSE"):
            require(False, "ORACLE_FALSE")


if __name__ == "__main__":
    unittest.main()
