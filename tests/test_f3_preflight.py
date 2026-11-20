"""F3 preflight tests: isolated F1 databases; no migration or production paths."""
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


e1 = load("e1_fixture", "tools/e1.py")
f3 = load("f3_preflight", "fixtures/f3_preflight.py")


class F3PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="f3-test-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "historical.sqlite"
        e1.initialize(self.path)

    def update(self, sql, args=()):
        with sqlite3.connect(self.path) as con:
            con.execute(sql, args)

    def test_valid_historical_codes_are_canonicalized_without_writing(self):
        before = self.path.read_bytes()
        result = f3.inspect(self.path)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(
            result["locations"],
            [{"location_id": "loc-north", "canonical": "NORTH"},
             {"location_id": "loc-south", "canonical": "SOUTH"}],
        )
        self.assertEqual(before, self.path.read_bytes())

    def test_collision_is_rejected_without_merging_ids(self):
        self.update("UPDATE location SET code = ? WHERE id = 'loc-south'", (" north ",))
        result = f3.inspect(self.path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"], [
            {"code": "F3_CODE_COLLISION", "location_id": "loc-south",
             "other_id": "loc-north", "canonical": "NORTH"}
        ])
        self.assertEqual(len(result["locations"]), 2)

    def test_invalid_and_empty_codes_are_rejected(self):
        for code in ("   ", "Café", "NORTH\\t", "NORTH_1"):
            with self.subTest(code=code):
                self.update("UPDATE location SET code = ? WHERE id = 'loc-south'", (code,))
                result = f3.inspect(self.path)
                self.assertFalse(result["ok"])
                self.assertEqual(result["issues"][0]["code"], "F3_INVALID_CODE")

    def test_missing_database_is_not_created(self):
        missing = Path(self.tmp.name) / "absent.sqlite"
        with self.assertRaises(FileNotFoundError):
            f3.inspect(missing)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
