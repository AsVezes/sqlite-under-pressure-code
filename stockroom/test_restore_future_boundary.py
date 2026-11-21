"""CP10 negative control: a backup ahead of the live receipt boundary is refused."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .backup import capture, validate, verify_bundle
from .restore import rehearse
from .test_backup import ready
from .transfer import Transfer
from .tune import copy_database
from .writer import submit


class RestoreFutureBoundaryTests(unittest.TestCase):
    def test_future_receipt_boundary_refused_without_selection(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            baseline = validate(live)
            future = root / "future.db"
            copy_database(live, future)
            submit(future, Transfer("future-only", "item-bolt",
                                    "loc-north", "loc-south", 1))
            bundle = Path(capture(future, root)["bundle"])
            verified, _manifest = verify_bundle(bundle)
            self.assertTrue(verified["ledger"]["ok"])
            self.assertEqual(verified["watermark"], 1)
            with self.assertRaisesRegex(ValueError, "ahead of the source"):
                rehearse(live, bundle, root)
            self.assertEqual(list(root.glob("stockroom-restore-*")), [])
            self.assertEqual(validate(live), baseline)
            self.assertEqual(list(root.rglob("selection.json")), [])
