"""CP10 negative control: a valid backup with altered opening is not this ledger's history."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .backup import capture, verify_bundle
from .environment import connect
from .restore import rehearse
from .test_backup import ready
from .tune import copy_database


class RestoreOpeningPrefixTests(unittest.TestCase):
    def test_valid_foreign_opening_is_refused_without_selection(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            fork = root / "alternate-opening.db"
            copy_database(live, fork)
            with closing(connect(fork)) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    for table in ("opening_balance", "stock_balance"):
                        db.execute(
                            f"UPDATE {table} SET quantity=quantity+1 "
                            "WHERE item_id='item-bolt' AND location_id='loc-north'"
                        )
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise

            bundle = Path(capture(fork, root)["bundle"])
            verified, _manifest = verify_bundle(bundle)
            self.assertTrue(verified["ledger"]["ok"])
            with self.assertRaisesRegex(ValueError, "opening balances differ"):
                rehearse(live, bundle, root)
            self.assertEqual(list(root.glob("stockroom-restore-*")), [])
