"""L13 regression: real SQLite BUSY/CONSTRAINT and fail-closed retry policy."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from l13_retry_budget import retry_busy, run


class L13RetryTests(unittest.TestCase):
    def test_disposable_integration(self):
        result = run()
        self.assertEqual(result["status"], "pass", result)
        self.assertTrue(all(result["oracles"].values()))
        self.assertEqual(result["retry_history"][0]["code"] & 255, sqlite3.SQLITE_BUSY)
        self.assertEqual(result["retry_history"][1]["result"], "ok")
        self.assertIn("sqlite_source_id", result["environment"])

    def test_budget_one_does_not_wait_or_retry(self):
        with tempfile.TemporaryDirectory(prefix="l13-test-") as root:
            path = Path(root) / "test.sqlite3"
            a = sqlite3.connect(path, isolation_level=None, timeout=0)
            b = sqlite3.connect(path, isolation_level=None, timeout=0)
            try:
                a.execute("CREATE TABLE t(x INTEGER)")
                a.execute("BEGIN IMMEDIATE")
                waits = []
                def acquire():
                    b.execute("BEGIN IMMEDIATE")
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    retry_busy(acquire, now=lambda: 0, deadline=10,
                               wait=lambda: waits.append("unexpected"), attempts=1)
                self.assertEqual(caught.exception.sqlite_errorcode & 255, sqlite3.SQLITE_BUSY)
                self.assertEqual(waits, [])
                self.assertFalse(b.in_transaction)
            finally:
                a.rollback()
                b.close()
                a.close()

    def test_non_busy_constraint_never_waits(self):
        with tempfile.TemporaryDirectory(prefix="l13-test-") as root:
            connection = sqlite3.connect(Path(root) / "test.sqlite3", isolation_level=None)
            try:
                connection.execute("CREATE TABLE t(x INTEGER UNIQUE)")
                connection.execute("INSERT INTO t VALUES(1)")
                attempts = []
                waits = []
                def duplicate():
                    attempts.append(1)
                    connection.execute("INSERT INTO t VALUES(1)")
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    retry_busy(duplicate, now=lambda: 0, deadline=10,
                               wait=lambda: waits.append(1), attempts=5)
                self.assertEqual(caught.exception.sqlite_errorcode & 255, sqlite3.SQLITE_CONSTRAINT)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(waits, [])
                self.assertEqual(connection.execute("SELECT count(*) FROM t").fetchone()[0], 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
