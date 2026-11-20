from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from .environment import connect, initialize_workspace
from .ledger import check_ledger, initialize_ledger, write_transaction
from .transfer import MAX_BALANCE, Transfer, apply_in_transaction, transfer


def sample(identifier="tx-001", quantity=3):
    return Transfer(identifier, "item-bolt", "loc-north", "loc-south", quantity)


class TransferTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(initialize_workspace(Path(directory.name))["database"])
        initialize_ledger(self.database)

    def state(self, quantities, transfers):
        verdict = check_ledger(self.database)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual([row["quantity"] for row in verdict["balances"]], quantities)
        self.assertEqual(verdict["transfers"], transfers)
        self.assertEqual(verdict["journal_entries"], transfers * 2)

    def test_cli_transfers_and_reopened_check_agrees(self):
        p = subprocess.run(
            [sys.executable, "-m", "stockroom", "transfer", str(self.database),
             "tx-001", "item-bolt", "loc-north", "loc-south", "3"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(json.loads(p.stdout)["status"], "committed")
        self.state([7, 5, 4, 8], 1)

    def test_failure_after_debit_is_invisible_after_reopen(self):
        with self.assertRaisesRegex(RuntimeError, "after debit"):
            transfer(self.database, sample(), fail_after_debit=True)
        self.state([10, 2, 4, 8], 0)

    def test_insufficient_stock_and_missing_position_leave_no_rows(self):
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            transfer(self.database, sample(quantity=11))
        with self.assertRaises(sqlite3.IntegrityError):
            transfer(self.database, Transfer("tx-missing", "item-bolt", "loc-north", "nowhere", 1))
        self.state([10, 2, 4, 8], 0)

    def test_duplicate_id_is_an_error_and_has_no_repeated_effect(self):
        transfer(self.database, sample())
        with self.assertRaises(sqlite3.IntegrityError):
            transfer(self.database, sample())
        self.state([7, 5, 4, 8], 1)

    def test_savepoint_reverts_one_failure_and_preserves_other_work(self):
        with closing(connect(self.database)) as db:
            with write_transaction(db):
                apply_in_transaction(db, sample())
                with self.assertRaisesRegex(RuntimeError, "after debit"):
                    apply_in_transaction(db, sample("tx-failed"), fail_after_debit=True)
                self.assertTrue(db.in_transaction)
                apply_in_transaction(db, sample("tx-002", 2))
        self.state([5, 7, 4, 8], 2)

    def test_parent_rollback_reverts_a_released_savepoint(self):
        with closing(connect(self.database)) as db:
            db.execute("BEGIN IMMEDIATE")
            apply_in_transaction(db, sample())
            db.execute("ROLLBACK")
        self.state([10, 2, 4, 8], 0)

    def test_application_does_not_coerce_quantity_or_accept_bad_ids(self):
        for value in (None, False, True, "3", 3.0, 0, -1, 1_000_000_001):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Quantity"):
                sample(quantity=value)
        for bad in ("", " ", " tx-001", "x\x00y", "a/b", 42):
            with self.subTest(identifier=bad), self.assertRaisesRegex(ValueError, "canonical identifier"):
                sample(identifier=bad)
        with self.assertRaisesRegex(ValueError, "must differ"):
            Transfer("tx-same", "item-bolt", "loc-north", "loc-north", 1)
        self.state([10, 2, 4, 8], 0)

    def test_balance_overflow_rolls_back_the_source_debit(self):
        with closing(connect(self.database)) as db:
            with write_transaction(db):
                for table in ("opening_balance", "stock_balance"):
                    db.execute(
                        f"UPDATE {table} SET quantity=? WHERE item_id='item-bolt' AND location_id='loc-south'",
                        (MAX_BALANCE,),
                    )
        with self.assertRaisesRegex(ValueError, "overflow"):
            transfer(self.database, sample())
        self.state([10, MAX_BALANCE, 4, 8], 0)
