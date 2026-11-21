"""CP10: a failed atomic pointer replacement leaves no staged selection."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .restore import select, selected


class SelectionAtomicityTests(unittest.TestCase):
    def test_replace_failure_preserves_original_and_removes_staging(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pointer = root / "selection.json"
            original = root / "live.db"
            candidate = root / "candidate.db"
            select(pointer, original)

            actual_replace = Path.replace

            def reject_pointer_replace(path, target):
                if path == pointer.with_suffix(".next"):
                    raise OSError("injected replace failure")
                return actual_replace(path, target)

            with patch.object(Path, "replace", autospec=True, side_effect=reject_pointer_replace):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    select(pointer, candidate)

            self.assertEqual(selected(pointer), original)
            self.assertFalse(pointer.with_suffix(".next").exists())

    def test_first_replace_failure_does_not_create_pointer(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pointer = root / "selection.json"
            with patch.object(Path, "replace", side_effect=OSError("injected replace failure")):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    select(pointer, root / "candidate.db")
            self.assertFalse(pointer.exists())
            self.assertFalse(pointer.with_suffix(".next").exists())
