from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .environment import connect, initialize_workspace
from .ledger import check_ledger, initialize_ledger
from .storage import profile
from .transfer import Transfer, transfer


class StorageTests(unittest.TestCase):
    def test_profiles_and_two_views_with_same_ledger(self):
        with TemporaryDirectory() as directory:
            path = Path(initialize_workspace(Path(directory))["database"])
            initialize_ledger(path)
            self.assertEqual(profile(path, "delete")["journal"], "delete")
            self.assertEqual(profile(path, "wal"),
                             {"journal": "wal", "synchronous": 2, "foreign_keys": 1})
            with closing(connect(path, read_only=True)) as reader:
                query = "SELECT quantity FROM stock_balance WHERE item_id='item-bolt' AND location_id='loc-north'"
                reader.execute("BEGIN")
                self.assertEqual(reader.execute(query).fetchone(), (10,))
                transfer(path, Transfer("t1", "item-bolt", "loc-north", "loc-south", 3))
                self.assertEqual(reader.execute(query).fetchone(), (10,))
                reader.execute("ROLLBACK")
                self.assertEqual(reader.execute(query).fetchone(), (7,))
            self.assertTrue(check_ledger(path)["ok"])

    def test_checkpoint_progress_and_extended_errors(self):
        import sqlite3
        from .observe import observe
        with TemporaryDirectory() as directory:
            path = Path(initialize_workspace(Path(directory))["database"])
            initialize_ledger(path)
            profile(path, "wal")
            with closing(connect(path, timeout=0)) as first, closing(connect(path, timeout=0)) as second:
                first.execute("BEGIN IMMEDIATE")
                with self.assertRaises(sqlite3.OperationalError) as busy:
                    second.execute("BEGIN IMMEDIATE")
                self.assertEqual(busy.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                first.execute("ROLLBACK")
                first.execute("BEGIN")
                first.execute("SELECT * FROM location").fetchall()
                transfer(path, Transfer("t1", "item-bolt", "loc-north", "loc-south", 1))
                with self.assertRaises(sqlite3.OperationalError) as stale:
                    first.execute("UPDATE location SET code=code")
                self.assertEqual(stale.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY_SNAPSHOT)
                during = observe(path)["checkpoint"]
                self.assertLess(during["backfilled"], during["frames"])
                first.execute("ROLLBACK")
                after = observe(path)["checkpoint"]
                self.assertEqual(after["backfilled"], after["frames"])
                first.executescript("CREATE TEMP TABLE sample(value); INSERT INTO sample VALUES (1),(2);")
                cursor = first.execute("SELECT value FROM sample")
                self.assertEqual(cursor.fetchone(), (1,))
                with self.assertRaises(sqlite3.OperationalError) as locked:
                    first.execute("DROP TABLE sample")
                self.assertEqual(locked.exception.sqlite_errorcode, sqlite3.SQLITE_LOCKED)
                cursor.close()
                first.execute("DROP TABLE sample")
            self.assertTrue(check_ledger(path)["ok"])
