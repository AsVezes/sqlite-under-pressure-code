"""F3 preflight regression: SQLite TEXT affinity does not prohibit BLOB values."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

e1 = load("e1_blob_fixture", "tools/e1.py")
f3 = load("f3_blob_preflight", "fixtures/f3_preflight.py")

class F3NonTextTests(unittest.TestCase):
    def test_blob_code_is_rejected_without_modifying_fixture(self):
        with tempfile.TemporaryDirectory(prefix="f3-blob-") as directory:
            path = Path(directory) / "historical.sqlite"
            e1.initialize(path)
            with sqlite3.connect(path) as con:
                con.execute("UPDATE location SET code = ? WHERE id = 'loc-south'",
                            (sqlite3.Binary(b"north"),))
                self.assertEqual(con.execute(
                    "SELECT typeof(code) FROM location WHERE id = 'loc-south'"
                ).fetchone()[0], "blob")
            before = path.read_bytes()
            result = f3.inspect(path)
            self.assertFalse(result["ok"])
            self.assertEqual(result["issues"], [
                {"code": "F3_INVALID_CODE", "location_id": "loc-south"}
            ])
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(len(result["locations"]), 2)
            self.assertIsNone(result["locations"][1]["canonical"])

if __name__ == "__main__":
    unittest.main()
