"""CP10 negative control: equal receipt boundaries do not prove common history."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .backup import capture, validate, verify_bundle
from .restore import rehearse
from .test_backup import ready
from .transfer import Transfer
from .tune import copy_database
from .writer import submit


class RestoreDivergentPrefixTests(unittest.TestCase):
    def test_equal_watermarks_with_different_receipts_are_refused(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            candidate = root / "candidate.db"
            copy_database(live, candidate)
            submit(live, Transfer("live-only", "item-bolt",
                                  "loc-north", "loc-south", 1))
            submit(candidate, Transfer("candidate-only", "item-bolt",
                                       "loc-north", "loc-south", 1))
            original = validate(live)
            bundle = Path(capture(candidate, root)["bundle"])
            verified, _manifest = verify_bundle(bundle)
            self.assertTrue(verified["ledger"]["ok"])
            self.assertEqual(verified["watermark"], original["watermark"])
            with self.assertRaisesRegex(ValueError, "receipt history diverges"):
                rehearse(live, bundle, root)
            self.assertEqual(validate(live), original)
            self.assertEqual(list(root.glob("stockroom-restore-*")), [])
            self.assertEqual(list(root.rglob("selection.json")), [])
