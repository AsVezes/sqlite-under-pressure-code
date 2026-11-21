"""CP10: a source receipt-boundary change during rehearsal must undo selection."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .backup import capture, validate
from .restore import rehearse
from .test_backup import ready


class RestoreSourceBoundaryTests(unittest.TestCase):
    def test_source_watermark_change_returns_pointer_to_live(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            before = validate(live)
            bundle = Path(capture(live, root)["bundle"])
            real_validate = validate
            calls = []

            def changed_source_boundary(path):
                state = real_validate(path)
                calls.append(Path(path))
                # Only the final source recheck is altered. The bundle and
                # restored database remain valid throughout the rehearsal.
                if Path(path) == live and calls.count(live) == 2:
                    return {**state, "watermark": state["watermark"] + 1}
                return state

            with patch("stockroom.restore.validate", side_effect=changed_source_boundary):
                with self.assertRaisesRegex(ValueError, "source changed during the rehearsal"):
                    rehearse(live, bundle, root)

            candidates = list(root.glob("stockroom-restore-*"))
            self.assertEqual(len(candidates), 1)
            pointer = candidates[0] / "selection.json"
            self.assertTrue(pointer.is_file())
            from .restore import selected
            self.assertEqual(selected(pointer), live)
            self.assertEqual(validate(live), before)
