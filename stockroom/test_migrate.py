from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .environment import connect, initialize_workspace
from .ledger import check_ledger, initialize_ledger
from .migrate import step
from .report import measure
from .transfer import Transfer
from .writer import install, submit


class MigrationTests(unittest.TestCase):
    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = Path(initialize_workspace(Path(d.name))["database"])
        initialize_ledger(self.path)
        install(self.path)
        submit(self.path, Transfer("old", "item-bolt", "loc-north", "loc-south", 3))

    def test_batch_and_rebuild_rollback_then_compatible_dependencies(self):
        with closing(connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE location_log(id TEXT);
                CREATE VIEW location_view AS SELECT id,code FROM location;
                CREATE TRIGGER location_logger AFTER UPDATE ON location
                BEGIN INSERT INTO location_log VALUES(new.id); END;
            """)
        def fail(phase):
            raise RuntimeError(phase)
        with self.assertRaisesRegex(RuntimeError, "batch"):
            step(self.path, interrupt=fail)
        self.assertEqual(step(self.path)["cursor"], 1)
        self.assertEqual(step(self.path)["cursor"], 2)
        before = measure(self.path, "item-bolt")["sha256"]
        with self.assertRaisesRegex(RuntimeError, "rebuild"):
            step(self.path, interrupt=fail)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT code FROM location_view WHERE id='loc-north'").fetchone(), (" North ",))
        self.assertEqual(step(self.path)["schema"], 2)
        self.assertEqual(measure(self.path, "item-bolt")["sha256"], before)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT code,code_history FROM location WHERE id='loc-north'").fetchone(), ("NORTH", " North "))
            db.execute("UPDATE location SET code='NORTH-2' WHERE id='loc-north'")
            self.assertEqual(db.execute("SELECT * FROM location_log").fetchone(), ("loc-north",))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(submit(self.path, Transfer("new", "item-bolt", "loc-south", "loc-north", 1))["receipt"], 2)
        self.assertTrue(check_ledger(self.path)["ok"])

    def test_changed_input_and_collision_refuse_before_promotion(self):
        step(self.path)
        with closing(connect(self.path)) as db:
            db.execute("UPDATE location SET code='North' WHERE id='loc-south'")
        with self.assertRaisesRegex(ValueError, "collision"):
            step(self.path)
        with closing(connect(self.path)) as db:
            db.execute("UPDATE location SET code='Other' WHERE id='loc-south'")
        with self.assertRaisesRegex(ValueError, "input changed"):
            step(self.path)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (1,))
            db.execute("PRAGMA user_version=999")
        with self.assertRaisesRegex(ValueError, "v999"):
            step(self.path)
