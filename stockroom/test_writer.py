from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest

from .environment import connect, initialize_workspace
from .ledger import check_ledger, initialize_ledger
from .storage import profile
from .transfer import Transfer, transfer
from .writer import install, run_queue, submit, watermark


class WriterTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(initialize_workspace(Path(scratch.name))["database"])
        initialize_ledger(self.path)
        profile(self.path, "wal")
        self.request = Transfer("op-1", "item-bolt", "loc-north", "loc-south", 3)

    def test_old_commit_becomes_receipt_then_retry_is_deduplicated(self):
        transfer(self.path, self.request)
        self.assertEqual(install(self.path)["receipt_count"], 1)
        self.assertEqual(install(self.path)["receipt_count"], 1)
        replay = submit(self.path, self.request)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt"], 1)
        with self.assertRaisesRegex(ValueError, "different payload"):
            submit(self.path, Transfer("op-1", "item-bolt", "loc-north", "loc-south", 2))
        with closing(connect(self.path)) as db:
            self.assertEqual(watermark(db), 1)
        self.assertTrue(check_ledger(self.path)["ok"])

    def test_failed_install_rolls_back_receipt_schema_and_backfill(self):
        # A conflicting trigger must not leave an installed receipt table behind.
        transfer(self.path, self.request)
        with closing(connect(self.path)) as db:
            db.execute("""CREATE TRIGGER record_transfer_receipt AFTER INSERT ON transfer
                          BEGIN SELECT 1; END""")
        with self.assertRaisesRegex(ValueError, "receipt trigger"):
            install(self.path)
        with closing(connect(self.path)) as db:
            names = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name='receipt'"
            )}
            self.assertEqual(names, set())
            self.assertEqual(db.execute("SELECT count(*) FROM transfer").fetchone()[0], 1)
        self.assertTrue(check_ledger(self.path)["ok"])

    def test_held_writer_cannot_change_state_and_budget_is_classified(self):
        install(self.path)
        with closing(connect(self.path)) as db:
            db.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.OperationalError) as failure:
                submit(self.path, self.request, 25)
            self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
            self.assertIn("retry", [row["phase"] for row in failure.exception.events])
            self.assertNotIn("work", [row["phase"] for row in failure.exception.events])
            db.execute("ROLLBACK")
        self.assertEqual(check_ledger(self.path)["transfers"], 0)
        self.assertEqual(submit(self.path, self.request)["receipt"], 1)

    def test_two_clients_then_returned_receipt_and_fifo(self):
        install(self.path)
        ready = threading.Barrier(2)
        outcomes = []
        errors = []
        def client():
            try:
                ready.wait(timeout=5)
                outcomes.append(submit(self.path, self.request, 500))
            except Exception as exc:
                errors.append(exc)
        workers = [threading.Thread(target=client) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(sorted(row["replayed"] for row in outcomes), [False, True])
        more = [Transfer(f"op-{i}", "item-bolt", "loc-north", "loc-south", 1)
                for i in range(2, 4)]
        self.assertEqual([row["receipt"] for row in run_queue(self.path, more)], [2, 3])
        self.assertTrue(check_ledger(self.path)["ok"])
