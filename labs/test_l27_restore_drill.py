"""L27/C24: exercise the published restore drill and its fail-closed gates.

All databases are synthetic and created under TemporaryDirectory. Run with
python -m unittest discover -s labs -p 'test_l27_restore_drill.py' -v
and repeat with python -O; neither mode may bypass validation.
"""
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).with_name("l27_restore_drill.py")


def load_lab():
    spec = importlib.util.spec_from_file_location("l27_restore_drill", LAB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class L27RestoreRegression(unittest.TestCase):
    def test_published_entry_point_normal_and_optimized(self):
        engines = []
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable]
                if optimized:
                    command.append("-O")
                command.append(str(LAB))
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=40,
                    check=False,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"{command!r}\nstdout={result.stdout}\nstderr={result.stderr}",
                )
                self.assertEqual(result.stderr, "")
                data = json.loads(result.stdout)
                self.assertEqual(data["lab"], "L27")
                self.assertEqual(data["backup"], data["restored"])
                self.assertEqual(data["backup"]["integrity"], "ok")
                self.assertEqual(data["backup"]["fk"], [])
                self.assertEqual(data["backup"]["schema"], 1)
                self.assertEqual(data["backup"]["balance"], 10)
                self.assertEqual(data["backup"]["ledger"], 10)
                self.assertEqual(data["backup"]["watermark"], 1)
                self.assertEqual(data["smoke_watermark"], 2)
                self.assertIs(data["backup_preserved"], True)
                self.assertEqual(data["negative_rejections"], {
                    "digest": "digest mismatch",
                    "semantic": "business invariant failure",
                    "schema": "incompatible schema",
                })
                self.assertTrue(data["sqlite_version"])
                self.assertTrue(data["sqlite_source_id"])
                self.assertTrue(data["python"])
                self.assertTrue(data["platform"])
                self.assertGreaterEqual(data["elapsed_ms"], 0)
                engines.append((data["sqlite_version"], data["sqlite_source_id"]))
        self.assertEqual(engines[0], engines[1])

    def test_wrong_digest_rejected_before_database_open(self):
        lab = load_lab()
        with tempfile.TemporaryDirectory(prefix="l27-negative-") as directory:
            path = Path(directory) / "not-a-database.db"
            path.write_bytes(b"synthetic invalid header")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "^digest mismatch$"):
                lab.validate(path, "0" * 64, 1)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_valid_digest_does_not_override_foreign_key_or_watermark(self):
        lab = load_lab()
        with tempfile.TemporaryDirectory(prefix="l27-negative-") as directory:
            path = Path(directory) / "fixture.db"
            with sqlite3.connect(path) as db:
                db.executescript("""
                    PRAGMA user_version=1;
                    CREATE TABLE account(id INTEGER PRIMARY KEY, balance INTEGER NOT NULL);
                    CREATE TABLE ledger(id INTEGER PRIMARY KEY, account_id INTEGER
                        REFERENCES account(id), delta INTEGER NOT NULL);
                    CREATE TABLE metadata(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                    INSERT INTO account VALUES(1,10);
                    INSERT INTO ledger VALUES(1,1,10);
                    INSERT INTO metadata VALUES('watermark',1);
                """)
            with self.assertRaisesRegex(RuntimeError, "^watermark mismatch$"):
                lab.validate(path, lab.digest(path), 2)
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO ledger VALUES(2,999,0)")
                db.commit()
            with self.assertRaisesRegex(RuntimeError, "^foreign key failure$"):
                lab.validate(path, lab.digest(path), 1)


if __name__ == "__main__":
    unittest.main()
