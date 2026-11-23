"""Regression checks for L29/C26-C27; run: python3 -m unittest discover -s labs -p 'test_l29*.py' -v.

All databases are disposable. The lab's Event handshake, not elapsed time,
establishes the contention order. Run again under python3 -O.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from l29_diagnosis import lock_case, plan_case


class L29Regression(unittest.TestCase):
    def test_lock_contention_and_release(self):
        with tempfile.TemporaryDirectory(prefix="test-l29-lock-") as root:
            path = Path(root) / "lock.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, amount INTEGER NOT NULL)")
                db.execute("INSERT INTO items VALUES (1, 1)")
            result = lock_case(path)
            self.assertEqual(result["negative_busy_code"], sqlite3.SQLITE_BUSY)
            self.assertTrue(result["positive_lock_released"])
            self.assertEqual(result["final_amount"], 2)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT amount FROM items WHERE id=1").fetchone(), (2,))
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_query_diagnosis_preserves_answer(self):
        with tempfile.TemporaryDirectory(prefix="test-l29-plan-") as root:
            path = Path(root) / "plan.sqlite"
            result = plan_case(path)
            self.assertEqual(result["rows"], 10000)
            self.assertEqual(result["matches"], 100)
            self.assertTrue(any("SCAN events" in p for p in result["plan_before"]))
            self.assertTrue(any("USING COVERING INDEX events_category_idx" in p
                                for p in result["plan_after"]))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM events WHERE category='rare'").fetchone(), (100,))
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))


if __name__ == "__main__":
    unittest.main()
