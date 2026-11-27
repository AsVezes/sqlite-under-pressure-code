"""Causal, adversarial tests for L30's receipt application and rejection.

All databases are disposable. Tests also run under python -O; no assertion-based
application safety checks are relied on by the laboratory itself.
"""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import l30_transfer_drill as lab


class ReceiptReplayTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="l30-causal-")
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "fixture.sqlite"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(
                "CREATE TABLE receipts(op_id INTEGER PRIMARY KEY, delta INTEGER NOT NULL);"
                "CREATE TABLE balance(amount INTEGER NOT NULL);"
                "INSERT INTO balance VALUES(0);"
            )
            self.assertIs(lab.submit_receipt(db, 5, 1), True)
        self.expected = [(5, 1)]
        self.assertEqual(lab.check(self.path, self.expected), self.expected)

    def test_replay_and_actual_conflict_share_write_path(self):
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIs(lab.submit_receipt(db, 5, 1), False)
            self.assertEqual(lab.check(self.path, self.expected), self.expected)
            self.assertIs(lab.reject_conflicting_receipt(
                db, self.path, self.expected, 5, 2), True)
            self.assertFalse(db.in_transaction)
            self.assertEqual(lab.check(self.path, self.expected), self.expected)
            self.assertIs(lab.submit_receipt(db, 6, 1), True)
        self.assertEqual(lab.check(self.path, [(5, 1), (6, 1)]),
                         [(5, 1), (6, 1)])

    def test_ignore_only_mutation_must_be_detected(self):
        def unsafe_ignore(db, op_id, delta):
            db.execute("INSERT OR IGNORE INTO receipts VALUES(?,?)", (op_id, delta))
            return False

        with closing(sqlite3.connect(self.path)) as db:
            with patch.object(lab, "apply_receipt", side_effect=unsafe_ignore):
                with self.assertRaisesRegex(RuntimeError,
                                            "negative control: conflicting receipt accepted"):
                    lab.reject_conflicting_receipt(db, self.path, self.expected, 5, 2)
            self.assertFalse(db.in_transaction)
        self.assertEqual(lab.check(self.path, self.expected), self.expected)

    def test_wrong_error_cannot_pass_as_conflict(self):
        with closing(sqlite3.connect(self.path)) as db:
            with patch.object(lab, "apply_receipt",
                              side_effect=ValueError("synthetic unrelated fault")):
                with self.assertRaisesRegex(RuntimeError,
                                            "negative control: conflict failed for the wrong reason"):
                    lab.reject_conflicting_receipt(db, self.path, self.expected, 5, 2)
            self.assertFalse(db.in_transaction)
        self.assertEqual(lab.check(self.path, self.expected), self.expected)

    def test_side_effect_then_conflict_is_rolled_back(self):
        def flawed_effect_then_reject(db, op_id, delta):
            db.execute("UPDATE balance SET amount=amount+99")
            raise ValueError("operation ID already committed with a different payload")

        with closing(sqlite3.connect(self.path)) as db:
            with patch.object(lab, "apply_receipt", side_effect=flawed_effect_then_reject):
                self.assertTrue(lab.reject_conflicting_receipt(
                    db, self.path, self.expected, 5, 2))
            self.assertFalse(db.in_transaction)
        self.assertEqual(lab.check(self.path, self.expected), self.expected)

    def test_invariant_rejects_missing_balance_row(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM balance")
            db.commit()
        with self.assertRaisesRegex(RuntimeError, "^balance invariant failed$"):
            lab.check(self.path, self.expected)

    def test_invariant_rejects_extra_balance_row(self):
        for extra in (1, 2):
            with self.subTest(extra=extra), closing(sqlite3.connect(self.path)) as db:
                db.execute("DELETE FROM balance WHERE rowid > 1")
                db.execute("INSERT INTO balance VALUES(?)", (extra,))
                db.commit()
                with self.assertRaisesRegex(RuntimeError, "^balance invariant failed$"):
                    lab.check(self.path, self.expected)

    def test_failed_balance_update_rolls_back_receipt(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM balance")
            db.commit()
            with self.assertRaisesRegex(RuntimeError,
                                        "balance row not updated exactly once"):
                lab.submit_receipt(db, 6, 1)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT op_id,delta FROM receipts").fetchall(),
                             self.expected)

    def test_missing_new_receipt_rolls_back_balance(self):
        controls = (
            ("BEFORE", "SELECT RAISE(IGNORE)"),
            ("AFTER", "DELETE FROM receipts WHERE op_id=NEW.op_id"),
        )
        for timing, action in controls:
            with self.subTest(timing=timing), closing(sqlite3.connect(self.path)) as db:
                db.execute(f"CREATE TRIGGER discard_receipt {timing} INSERT ON receipts "
                           f"BEGIN {action}; END")
                with self.assertRaisesRegex(RuntimeError, "receipt row missing or changed"):
                    lab.submit_receipt(db, 6, 2)
                self.assertFalse(db.in_transaction)
                self.assertEqual(lab.check(self.path, self.expected), self.expected)
                db.execute("DROP TRIGGER discard_receipt")


if __name__ == "__main__":
    unittest.main()
