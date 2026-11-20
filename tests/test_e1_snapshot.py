"""Deterministic WAL snapshot regression for E1/O1 (no timing sleeps)."""

import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "e1.py"
SPEC = importlib.util.spec_from_file_location("e1_snapshot", SCRIPT)
e1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e1)


class E1SnapshotTests(unittest.TestCase):
    def test_oracle_reads_one_snapshot_during_concurrent_wal_commit(self):
        with tempfile.TemporaryDirectory(prefix="e1-wal-snapshot-") as root:
            path = Path(root) / "f1 stockroom.sqlite"
            e1.initialize(path)
            real_connect = sqlite3.connect
            writer = real_connect(path)
            self.addCleanup(writer.close)
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0],
                             "wal")
            committed = []
            transfer_sql = """
                BEGIN IMMEDIATE;
                INSERT INTO transfer VALUES
                    ('tx-wal', 'item-bolt', 'loc-north', 'loc-south', 3);
                UPDATE stock_balance SET quantity = quantity - 3
                    WHERE item_id='item-bolt' AND location_id='loc-north';
                UPDATE stock_balance SET quantity = quantity + 3
                    WHERE item_id='item-bolt' AND location_id='loc-south';
                INSERT INTO journal_entry
                    (transfer_id, item_id, location_id, delta) VALUES
                    ('tx-wal', 'item-bolt', 'loc-north', -3),
                    ('tx-wal', 'item-bolt', 'loc-south', 3);
                COMMIT;
            """

            def connect_with_barrier(*args, **kwargs):
                reader = real_connect(*args, **kwargs)
                # O1 uses a read-only URI. Inject exactly one commit after
                # opening_balance has been read but before stock_balance.
                if kwargs.get("uri") is True:
                    def barrier(sql):
                        if (not committed
                                and "FROM stock_balance" in sql):
                            writer.executescript(transfer_sql)
                            committed.append(True)
                    reader.set_trace_callback(barrier)
                return reader

            with patch.object(e1.sqlite3, "connect", side_effect=connect_with_barrier):
                before = e1.inspect(path)
            self.assertEqual(committed, [True], "writer barrier never fired")
            self.assertTrue(before["ok"], before["errors"])
            self.assertEqual(before["transfers"], 0)
            self.assertEqual(before["journal_entries"], 0)
            self.assertEqual(
                [r["quantity"] for r in before["balances"]
                 if r["item_id"] == "item-bolt"],
                [10, 2],
            )

            # A fresh reader sees the committed state, not the pinned one.
            after = e1.inspect(path)
            self.assertTrue(after["ok"], after["errors"])
            self.assertEqual(after["transfers"], 1)
            self.assertEqual(after["journal_entries"], 2)
            self.assertEqual(
                [r["quantity"] for r in after["balances"]
                 if r["item_id"] == "item-bolt"],
                [7, 5],
            )


if __name__ == "__main__":
    unittest.main()
