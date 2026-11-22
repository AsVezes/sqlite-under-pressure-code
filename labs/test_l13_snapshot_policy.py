#!/usr/bin/env python3
"""L13: a stale WAL snapshot must restart its transaction, not retry in place."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from l13_retry_budget import retry_busy


class SnapshotRetryPolicyTests(unittest.TestCase):
    def test_stale_snapshot_not_retried(self):
        with tempfile.TemporaryDirectory(prefix="sqlite-l13-snapshot-") as directory:
            path = Path(directory) / "fixture.sqlite3"
            a = sqlite3.connect(path, isolation_level=None, timeout=0)
            b = sqlite3.connect(path, isolation_level=None, timeout=0)
            try:
                self.assertEqual(a.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                a.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
                a.execute("INSERT INTO t VALUES (1,0)")
                a.execute("BEGIN")
                self.assertEqual(a.execute("SELECT n FROM t").fetchone()[0], 0)
                b.execute("BEGIN IMMEDIATE")
                b.execute("UPDATE t SET n=1 WHERE id=1")
                b.execute("COMMIT")
                calls = []
                waits = []
                def promote():
                    calls.append("attempt")
                    return a.execute("UPDATE t SET n=n+1 WHERE id=1")
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    retry_busy(promote, now=lambda: 0, deadline=10,
                               wait=lambda: waits.append("wait"), attempts=5)
                self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY_SNAPSHOT)
                self.assertEqual(calls, ["attempt"])
                self.assertEqual(waits, [])
                self.assertEqual(a.execute("SELECT n FROM t").fetchone()[0], 0)
                a.execute("ROLLBACK")
                self.assertEqual(a.execute("SELECT n FROM t").fetchone()[0], 1)
                # Recovery is a new transaction, not an in-place statement retry.
                a.execute("BEGIN IMMEDIATE")
                a.execute("UPDATE t SET n=n+1 WHERE id=1")
                a.execute("COMMIT")
                self.assertEqual(b.execute("SELECT n FROM t").fetchone()[0], 2)
                self.assertEqual(a.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                if a.in_transaction:
                    a.execute("ROLLBACK")
                if b.in_transaction:
                    b.execute("ROLLBACK")
                a.close()
                b.close()


if __name__ == "__main__":
    unittest.main()
