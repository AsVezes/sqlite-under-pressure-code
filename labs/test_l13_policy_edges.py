"""L13 / C12: boundary tests for retry policy, using disposable SQLite fixtures."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from l13_retry_budget import retry_busy


class RetryPolicyBoundaryTests(unittest.TestCase):
    def test_deadline_equal_now_never_waits(self):
        with tempfile.TemporaryDirectory(prefix="l13-boundary-") as directory:
            path = Path(directory) / "busy.sqlite3"
            holder = sqlite3.connect(path, isolation_level=None, timeout=0)
            contender = sqlite3.connect(path, isolation_level=None, timeout=0)
            try:
                holder.execute("CREATE TABLE item(id INTEGER PRIMARY KEY)")
                holder.execute("BEGIN IMMEDIATE")
                holder.execute("INSERT INTO item VALUES (1)")
                calls = []
                waits = []
                def acquire():
                    calls.append("attempt")
                    contender.execute("BEGIN IMMEDIATE")
                with self.assertRaises(sqlite3.OperationalError) as captured:
                    retry_busy(acquire, now=lambda: 5, deadline=5,
                               wait=lambda: waits.append("wait"), attempts=4)
                self.assertEqual(captured.exception.sqlite_errorcode & 255, sqlite3.SQLITE_BUSY)
                self.assertEqual(calls, ["attempt"])
                self.assertEqual(waits, [])
                self.assertFalse(contender.in_transaction)
                holder.execute("ROLLBACK")
                self.assertEqual(contender.execute("SELECT count(*) FROM item").fetchone()[0], 0)
            finally:
                if holder.in_transaction:
                    holder.rollback()
                if contender.in_transaction:
                    contender.rollback()
                contender.close()
                holder.close()

    def test_non_sqlite_exception_is_not_retried(self):
        calls = []
        waits = []
        def operation():
            calls.append("attempt")
            raise ValueError("caller validation failed")
        with self.assertRaisesRegex(ValueError, "caller validation failed"):
            retry_busy(operation, now=lambda: 0, deadline=10,
                       wait=lambda: waits.append("wait"), attempts=5)
        self.assertEqual(calls, ["attempt"])
        self.assertEqual(waits, [])


if __name__ == "__main__":
    unittest.main()
