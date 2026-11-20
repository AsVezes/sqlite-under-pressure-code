import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from .environment import initialize_workspace, inspect_workspace, runtime_profile


class WorkspaceTests(unittest.TestCase):
    def test_exclusive_workspace_with_spaces_reopened_by_second_process(self):
        with tempfile.TemporaryDirectory(prefix="stockroom tests ") as directory:
            parent = Path(directory)
            first = initialize_workspace(parent)
            second = initialize_workspace(parent)
            path = Path(first["database"])
            self.assertIn(" ", str(path))
            self.assertNotEqual(first["workspace_id"], second["workspace_id"])
            p = subprocess.run(
                [sys.executable, "-m", "stockroom", "identity", str(path)],
                check=True, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(json.loads(p.stdout), inspect_workspace(path))
            self.assertEqual(json.loads(p.stdout)["workspace_id"], first["workspace_id"])
            self.assertEqual(path.parent.parent, parent.resolve())

    def test_missing_path_does_not_create_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong_path = Path(directory) / "wrong working directory" / "stockroom ledger.sqlite3"
            wrong_path.parent.mkdir()
            with self.assertRaises(ValueError):
                inspect_workspace(wrong_path)
            self.assertFalse(wrong_path.exists())

    def test_foreign_database_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "foreign.sqlite3"
            db = sqlite3.connect(path)
            db.close()
            with self.assertRaisesRegex(ValueError, "not a Stockroom Ledger"):
                inspect_workspace(path)

    def test_runtime_identifies_engine_and_reports_cli_separately(self):
        profile = runtime_profile()
        self.assertEqual(profile["sqlite_library"]["version"], sqlite3.sqlite_version)
        self.assertTrue(profile["sqlite_library"]["source_id"])
        self.assertIsInstance(profile["sqlite_cli"]["available"], bool)
