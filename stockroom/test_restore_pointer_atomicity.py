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
                if path.name == "selection.next":
                    raise OSError("injected replace failure")
                return actual_replace(path, target)

            with patch.object(Path, "replace", autospec=True, side_effect=reject_pointer_replace):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    select(pointer, candidate)

            self.assertEqual(selected(pointer), original)
            self.assertEqual(list(root.glob(".selection-*")), [])

    def test_first_replace_failure_does_not_create_pointer(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pointer = root / "selection.json"
            with patch.object(Path, "replace", side_effect=OSError("injected replace failure")):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    select(pointer, root / "candidate.db")
            self.assertFalse(pointer.exists())
            self.assertEqual(list(root.glob(".selection-*")), [])

    def test_partial_staging_write_failure_preserves_original(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pointer = root / "selection.json"
            original = root / "live.db"
            select(pointer, original)
            before = pointer.read_bytes()
            actual_write = Path.write_text

            def fail_after_partial_write(path, data, **kwargs):
                if path.name == "selection.next":
                    actual_write(path, data[:5], **kwargs)
                    raise OSError("injected partial staging write")
                return actual_write(path, data, **kwargs)

            with patch.object(Path, "write_text", autospec=True, side_effect=fail_after_partial_write):
                with self.assertRaisesRegex(OSError, "injected partial staging write"):
                    select(pointer, root / "candidate.db")

            self.assertEqual(pointer.read_bytes(), before)
            self.assertEqual(selected(pointer), original)
            self.assertEqual(list(root.glob(".selection-*")), [])


    def test_overlapping_replacements_use_distinct_staging_paths(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pointer = root / "selection.json"
            first, second = root / "first.db", root / "second.db"
            actual_replace = Path.replace
            paths = []

            def overlap(path, target):
                paths.append(path)
                if len(paths) == 1:
                    select(pointer, second)
                    self.assertEqual(selected(pointer), second)
                return actual_replace(path, target)

            with patch.object(Path, "replace", autospec=True, side_effect=overlap):
                select(pointer, first)
            self.assertEqual(len(set(paths)), 2)
            self.assertEqual(selected(pointer), first)
            self.assertEqual(list(root.glob(".selection-*")), [])
