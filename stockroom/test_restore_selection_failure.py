"""CP10: a selection failure after switching must return to the live source."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .backup import capture, validate
from .restore import rehearse, selected
from .test_backup import ready


class RestoreSelectionFailureTests(unittest.TestCase):
    def test_selection_error_after_candidate_switch_returns_to_source(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            before = validate(live)
            bundle = Path(capture(live, root)["bundle"])
            from . import restore as restore_module
            actual_select = restore_module.select
            calls = []

            def fail_after_switch(pointer, database):
                actual_select(pointer, database)
                calls.append(Path(database))
                if len(calls) == 2:
                    raise OSError("injected post-selection failure")

            with patch("stockroom.restore.select", side_effect=fail_after_switch):
                with self.assertRaisesRegex(OSError, "injected post-selection failure"):
                    rehearse(live, bundle, root)

            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0], live)
            self.assertNotEqual(calls[1], live)
            self.assertEqual(calls[2], live)
            pointer = calls[1].parent / "selection.json"
            self.assertEqual(selected(pointer), live)
            self.assertEqual(validate(live), before)


    def test_double_failure_preserves_both_diagnostics_and_candidate(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            bundle = Path(capture(live, root)["bundle"])
            from . import restore as restore_module
            actual_select = restore_module.select
            calls = []

            def fail_switch_and_return(pointer, database):
                calls.append(database)
                if len(calls) == 3:
                    raise OSError("return blocked")
                actual_select(pointer, database)
                if len(calls) == 2:
                    raise OSError("switch failed after replacement")

            with patch.object(restore_module, "select", side_effect=fail_switch_and_return):
                with self.assertRaisesRegex(
                    RuntimeError, "switch failed after replacement.*return blocked.*selection.json"
                ):
                    rehearse(live, bundle, root)
            candidate = calls[1]
            self.assertTrue(candidate.is_file())
            self.assertEqual(selected(candidate.parent / "selection.json"), candidate)
