"""CP10 negative control: a shorter candidate prefix must never match a source."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .backup import validate
from .restore import require_history_prefix
from .test_backup import ready
from .transfer import Transfer
from .tune import copy_database
from .writer import submit


class RestoreTruncatedPrefixTests(unittest.TestCase):
    def test_missing_candidate_receipt_is_rejected_without_mutation(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            candidate = root / "older.db"
            copy_database(live, candidate)
            submit(live, Transfer("newer-only", "item-bolt",
                                  "loc-north", "loc-south", 1))
            before_live = validate(live)
            before_candidate = validate(candidate)
            self.assertEqual(before_live["watermark"], 1)
            self.assertEqual(before_candidate["watermark"], 0)
            with self.assertRaises(ValueError):
                require_history_prefix(live, candidate, before_live["watermark"])
            self.assertEqual(validate(live), before_live)
            self.assertEqual(validate(candidate), before_candidate)
