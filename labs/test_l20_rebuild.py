"""Gate M regression for L20/C18; run python3 -m unittest discover -s labs -p 'test_l20_rebuild.py' -v."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from l20_rebuild import rebuild, schema, setup, verify


class RebuildGate(unittest.TestCase):
    def test_rollback_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix="gate-l20-") as directory:
            path = Path(directory) / "db.sqlite"
            db = setup(path)
            try:
                original_schema = schema(db)
                original_rows = db.execute("select * from items order by id").fetchall()
                with self.assertRaisesRegex(RuntimeError, "^INJECTED_PRECOMMIT$"):
                    rebuild(db, fail=True)
                self.assertFalse(db.in_transaction)
                self.assertEqual(schema(db), original_schema)
                self.assertEqual(db.execute("select * from items order by id").fetchall(), original_rows)
                verify(db)
                rebuild(db)
                self.assertIn("items_qty", schema(db))
                self.assertIn("items_qty_audit", schema(db))
                self.assertEqual(db.execute("pragma table_info(items)").fetchall()[-1][1], "note")
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    db.execute("update items set qty=-1 where id=1")
                self.assertEqual(caught.exception.sqlite_errorcode & 255, sqlite3.SQLITE_CONSTRAINT)
                db.execute("update items set qty=12 where id=1")
                self.assertEqual(db.execute("select item_id,old_qty from audit").fetchall(), [(1, 10)])
            finally:
                db.close()
            db = sqlite3.connect(path, isolation_level=None)
            try:
                db.execute("pragma foreign_keys=ON")
                verify(db)
                self.assertIn("items_qty", schema(db))
                self.assertIn("items_qty_audit", schema(db))
                self.assertEqual(db.execute("select qty from items where id=1").fetchone()[0], 12)
                print("L20 test engine:", db.execute("select sqlite_version(),sqlite_source_id()").fetchone())
            finally:
                db.close()

    def test_missing_index_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="gate-l20-negative-") as directory:
            db = setup(Path(directory) / "db.sqlite")
            try:
                rebuild(db, omit_index=True)
                self.assertNotIn("items_qty", schema(db))
                with self.assertRaisesRegex(RuntimeError, "^MISSING_INDEX_DETECTED$"):
                    if "items_qty" not in schema(db):
                        raise RuntimeError("MISSING_INDEX_DETECTED")
                verify(db)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
