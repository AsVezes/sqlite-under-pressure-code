"""E1/F1 tests use only temporary databases; no external dependencies."""

import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "e1.py"
SPEC = importlib.util.spec_from_file_location("e1", SCRIPT)
e1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e1)


class E1OracleTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="e1-test-")
        self.addCleanup(self.workspace.cleanup)
        self.path = Path(self.workspace.name) / "f1 stockroom.sqlite"
        e1.initialize(self.path)

    def sql(self, script):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(script)
        finally:
            connection.close()

    def test_baseline_passes_and_has_four_positions(self):
        result = e1.inspect(self.path)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["transfers"], 0)
        self.assertEqual(result["journal_entries"], 0)
        self.assertEqual(
            [(r["item_id"], r["location_id"], r["quantity"])
             for r in result["balances"]],
            [
                ("item-bolt", "loc-north", 10),
                ("item-bolt", "loc-south", 2),
                ("item-nut", "loc-north", 4),
                ("item-nut", "loc-south", 8),
            ],
        )

    def test_existing_file_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            e1.initialize(self.path)

    def test_failed_initialization_removes_partial_fixture(self):
        from unittest.mock import patch

        broken = Path(self.workspace.name) / "broken fixture.sqlite"
        invalid_sql = Path(self.workspace.name) / "invalid.sql"
        invalid_sql.write_text(
            "CREATE TABLE partial(id INTEGER);\nINVALID SQL;\n",
            encoding="utf-8",
        )
        with patch.object(e1, "SCHEMA", invalid_sql):
            with self.assertRaises(sqlite3.Error):
                e1.initialize(broken)
        self.assertFalse(broken.exists())
        # Failure must not affect the independently initialized baseline.
        self.assertTrue(e1.inspect(self.path)["ok"])

    def test_missing_file_is_not_created_by_checker(self):
        missing = Path(self.workspace.name) / "missing.sqlite"
        with self.assertRaises(FileNotFoundError):
            e1.inspect(missing)
        self.assertFalse(missing.exists())

    def test_nonnegative_but_incorrect_balance_fails(self):
        self.sql("""UPDATE stock_balance SET quantity = 11
                    WHERE item_id = 'item-bolt'
                    AND location_id = 'loc-north';""")
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn(
            "O1_BALANCE_MISMATCH:item-bolt:loc-north", result["errors"]
        )

    def test_partial_debit_fails_conservation(self):
        self.sql("""UPDATE stock_balance SET quantity = 7
                    WHERE item_id = 'item-bolt'
                    AND location_id = 'loc-north';""")
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_CONSERVATION:item-bolt", result["errors"])

    def test_nonnumeric_quantity_is_rejected_without_traceback(self):
        # Non-STRICT SQLite permits TEXT in INTEGER-affinity columns and the
        # simple CHECK(quantity >= 0) does not reject every TEXT value.
        self.sql("""UPDATE stock_balance SET quantity = 'abc'
                    WHERE item_id = 'item-bolt'
                    AND location_id = 'loc-north';""")
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_NONINTEGER_QUANTITY", result["errors"])

    def test_completed_transfer_and_two_journal_entries_pass(self):
        self.sql("""
            BEGIN;
            INSERT INTO transfer VALUES
                ('tx-001', 'item-bolt', 'loc-north', 'loc-south', 3);
            UPDATE stock_balance SET quantity = quantity - 3
                WHERE item_id = 'item-bolt' AND location_id = 'loc-north';
            UPDATE stock_balance SET quantity = quantity + 3
                WHERE item_id = 'item-bolt' AND location_id = 'loc-south';
            INSERT INTO journal_entry
                (transfer_id, item_id, location_id, delta) VALUES
                ('tx-001', 'item-bolt', 'loc-north', -3),
                ('tx-001', 'item-bolt', 'loc-south', 3);
            COMMIT;
        """)
        result = e1.inspect(self.path)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["transfers"], 1)
        self.assertEqual(result["journal_entries"], 2)

    def test_transfer_without_journal_is_rejected(self):
        self.sql("""
            INSERT INTO transfer VALUES
                ('tx-missing', 'item-bolt', 'loc-north', 'loc-south', 3);
        """)
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_JOURNAL_PAIR:tx-missing", result["errors"])

    def test_wrong_journal_pair_is_rejected_even_when_balances_match(self):
        self.sql("""
            BEGIN;
            INSERT INTO transfer VALUES
                ('tx-wrong', 'item-bolt', 'loc-north', 'loc-south', 3);
            UPDATE stock_balance SET quantity = 7
                WHERE item_id = 'item-bolt' AND location_id = 'loc-north';
            UPDATE stock_balance SET quantity = 5
                WHERE item_id = 'item-bolt' AND location_id = 'loc-south';
            INSERT INTO journal_entry
                (transfer_id, item_id, location_id, delta) VALUES
                ('tx-wrong', 'item-bolt', 'loc-north', -2),
                ('tx-wrong', 'item-bolt', 'loc-south', 2);
            COMMIT;
        """)
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_JOURNAL_PAIR:tx-wrong", result["errors"])
        self.assertTrue(any(error.startswith("O1_BALANCE_MISMATCH:")
                            for error in result["errors"]))

    def test_checker_does_not_change_database_bytes(self):
        before = self.path.read_bytes()
        result = e1.inspect(self.path)
        after = self.path.read_bytes()
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(before, after)

    def test_deleted_position_is_rejected_even_when_other_totals_unchanged(self):
        self.sql("""
            DELETE FROM stock_balance
            WHERE item_id = 'item-bolt' AND location_id = 'loc-south';
        """)
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_POSITION_SET", result["errors"])
        self.assertIn("O1_BALANCE_MISMATCH:item-bolt:loc-south", result["errors"])

    def test_journal_for_wrong_item_is_rejected(self):
        self.sql("""
            BEGIN;
            INSERT INTO transfer VALUES
                ('tx-cross-item', 'item-bolt', 'loc-north', 'loc-south', 3);
            INSERT INTO journal_entry
                (transfer_id, item_id, location_id, delta) VALUES
                ('tx-cross-item', 'item-nut', 'loc-north', -3),
                ('tx-cross-item', 'item-nut', 'loc-south', 3);
            COMMIT;
        """)
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_JOURNAL_PAIR:tx-cross-item", result["errors"])
        self.assertTrue(any(error.startswith("O1_BALANCE_MISMATCH:")
                            for error in result["errors"]))

    def test_orphan_journal_is_reported_with_foreign_keys_disabled(self):
        # Deliberately bypass connection-level FK enforcement to simulate an
        # externally damaged database. O1 must report both independent signals.
        connection = sqlite3.connect(self.path)
        try:
            # The SQLite build may choose a different FK default. Set the
            # bypass explicitly before any transaction, then verify it.
            connection.execute("PRAGMA foreign_keys = OFF")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 0)
            connection.execute(
                """INSERT INTO journal_entry
                   (transfer_id, item_id, location_id, delta)
                   VALUES ('tx-orphan', 'item-bolt', 'loc-north', -1)"""
            )
            connection.commit()
        finally:
            connection.close()
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertIn("O1_FOREIGN_KEY", result["errors"])
        self.assertIn("O1_ORPHAN_JOURNAL:tx-orphan", result["errors"])
        self.assertIn(
            "O1_BALANCE_MISMATCH:item-bolt:loc-north", result["errors"]
        )

    def test_balances_without_journal_fail_even_if_total_conserved(self):
        self.sql("""
            UPDATE stock_balance SET quantity = 9
                WHERE item_id = 'item-bolt' AND location_id = 'loc-north';
            UPDATE stock_balance SET quantity = 3
                WHERE item_id = 'item-bolt' AND location_id = 'loc-south';
        """)
        result = e1.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertTrue(any(e.startswith("O1_BALANCE_MISMATCH:")
                            for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
