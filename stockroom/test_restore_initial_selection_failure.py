"""CP10: an exception after the initial pointer write must restore the source."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .backup import capture, validate
from .restore import rehearse, selected
from .test_backup import ready


class RestoreInitialSelectionFailureTests(unittest.TestCase):
    def test_initial_selection_error_after_write_returns_to_source(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            before = validate(live)
            bundle = Path(capture(live, root)["bundle"])
            from . import restore as restore_module
            actual_select = restore_module.select
            calls = []

            def fail_after_first_write(pointer, database):
                actual_select(pointer, database)
                calls.append(Path(database))
                if len(calls) == 1:
                    raise OSError("injected initial selection failure")

            with patch("stockroom.restore.select", side_effect=fail_after_first_write):
                with self.assertRaisesRegex(OSError, "injected initial selection failure"):
                    rehearse(live, bundle, root)

            self.assertEqual(calls, [live, live])
            pointers = list(root.rglob("selection.json"))
            self.assertEqual(len(pointers), 1)
            self.assertEqual(selected(pointers[0]), live)
            self.assertEqual(validate(live), before)
