from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from .environment import connect, initialize_workspace, inspect_workspace
from .ledger import check_ledger, initialize_ledger


class LedgerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(initialize_workspace(Path(directory.name))["database"])

    def test_v1_uses_existing_workspace_and_loads_f1_for_o1(self):
        initial = inspect_workspace(self.database)
        result = initialize_ledger(self.database)
        self.assertEqual(result["workspace_id"], initial["workspace_id"])
        self.assertEqual(result["schema_version"], 1)
        before = hashlib.sha256(self.database.read_bytes()).digest()
        verdict = check_ledger(self.database)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["transfers"], 0)
        self.assertEqual(verdict["journal_entries"], 0)
        self.assertEqual([row["quantity"] for row in verdict["balances"]], [10, 2, 4, 8])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), before)
        with self.assertRaisesRegex(ValueError, "Expected.*v0"):
            # Initializing a v1 workspace must never reload its fixture.
            initialize_ledger(self.database)

    def test_schema_install_rolls_back_on_seed_failure(self):
        with patch("stockroom.ledger.seed_f1", side_effect=RuntimeError("seed failure")):
            with self.assertRaisesRegex(RuntimeError, "seed failure"):
                initialize_ledger(self.database)
        self.assertEqual(inspect_workspace(self.database)["schema_version"], 0)
        with closing(connect(self.database)) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_schema WHERE name='item'").fetchone())
        self.assertEqual(initialize_ledger(self.database)["schema_version"], 1)

    def test_schema_rejects_invalid_rows_without_coercing(self):
        initialize_ledger(self.database)
        with closing(connect(self.database)) as db:
            cases = [
                ("empty item", "INSERT INTO item VALUES(?,?)", ("", "new")),
                ("null location", "INSERT INTO location VALUES(?,?)", (None, "new")),
                ("numeric item id", "INSERT INTO item VALUES(?,?)", (37, "new")),
                ("missing reference", "INSERT INTO opening_balance VALUES(?,?,?)", ("missing", "loc-north", 1)),
                ("empty transfer", "INSERT INTO transfer VALUES(?,?,?,?,?)",
                 ("", "item-bolt", "loc-north", "loc-south", 2)),
                ("same location", "INSERT INTO transfer VALUES(?,?,?,?,?)",
                 ("tx-same", "item-bolt", "loc-north", "loc-north", 2)),
            ]
            for quantity in (None, "3", 3.0, 0, -1, 1_000_000_001):
                cases.append((repr(quantity), "INSERT INTO transfer VALUES(?,?,?,?,?)",
                              ("tx-bad", "item-bolt", "loc-north", "loc-south", quantity)))
            for name, sql, params in cases:
                with self.subTest(name=name), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql, params)
        self.assertTrue(check_ledger(self.database)["ok"])

    def test_o1_detects_projection_drift_in_valid_sqlite_file(self):
        initialize_ledger(self.database)
        with closing(connect(self.database)) as db:
            db.execute("UPDATE stock_balance SET quantity=quantity+1 WHERE item_id='item-bolt' AND location_id='loc-north'")
        verdict = check_ledger(self.database)
        self.assertFalse(verdict["ok"])
        self.assertIn("O1_BALANCE_MISMATCH:item-bolt:loc-north", verdict["errors"])
