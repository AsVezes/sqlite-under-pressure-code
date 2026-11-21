"""CP10: a silent failure to return the selection must not report success."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from stockroom import restore as module


class ReturnSelectionTests(TestCase):
    def test_silent_return_noop_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.db"
            candidate = root / "candidate" / "ledger.db"
            candidate.parent.mkdir()
            state = {"workspace_id": "same", "ledger": "same",
                     "watermark": 0, "source_id": "test"}
            real_select = module.select
            calls = []

            def incomplete_select(pointer, database):
                calls.append(database)
                if len(calls) < 3:
                    real_select(pointer, database)
                # Third call simulates a no-op without an exception.

            with (
                patch.object(module, "validate", return_value=state),
                patch.object(module, "restore", return_value=(candidate, state)),
                patch.object(module, "require_history_prefix"),
                patch.object(module, "smoke"),
                patch.object(module, "select", side_effect=incomplete_select),
            ):
                with self.assertRaisesRegex(RuntimeError, "return to source failed"):
                    module.rehearse(live, root, root)

            self.assertEqual(calls, [live, candidate, live])
            self.assertEqual(module.selected(candidate.parent / "selection.json"), candidate)
