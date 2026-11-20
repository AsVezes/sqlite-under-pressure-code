from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .backup import capture, digest, verify_bundle
from .environment import connect
from .restore import rehearse
from .test_backup import ready
from .transfer import Transfer
from .tune import copy_database
from .writer import submit


class RestoreTests(unittest.TestCase):
    def test_restore_cutover_return_and_unacceptable_candidate(self):
        with TemporaryDirectory() as t:
            root = Path(t)
            path = ready(root)
            bundle = Path(capture(path, root)["bundle"])
            submit(path, Transfer("later", "item-bolt", "loc-north", "loc-south", 1))
            result = rehearse(path, bundle, root)
            self.assertEqual(result["returned_to"], str(path))
            self.assertEqual(result["rpo_operations"], 1)
            self.assertGreater(result["rto_ns"], 0)
            candidate = bundle / "ledger.db"
            with closing(connect(candidate)) as db:
                db.execute("UPDATE stock_balance SET quantity=quantity+1 WHERE item_id='item-bolt'")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_bundle(bundle)
            manifest = bundle / "manifest.json"
            data = json.loads(manifest.read_text())
            data["sha256"] = digest(candidate)
            manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "ledger reconciliation failed"):
                rehearse(path, bundle, root)

    def test_divergent_prefix_refused_before_selection(self):
        for backup_id, backup_quantity, live_extra in (("fork", 1, False), ("fork", 1, True), ("live", 2, False)):
            with self.subTest(backup_id=backup_id, backup_quantity=backup_quantity, live_extra=live_extra):
                with TemporaryDirectory() as temp:
                    root = Path(temp)
                    live = ready(root)
                    fork = root / "fork.db"
                    copy_database(live, fork)
                    submit(fork, Transfer(backup_id, "item-bolt", "loc-north", "loc-south", backup_quantity))
                    submit(live, Transfer("live", "item-bolt", "loc-north", "loc-south", 1))
                    if live_extra:
                        submit(live, Transfer("extra", "item-bolt", "loc-north", "loc-south", 1))
                    bundle = Path(capture(fork, root)["bundle"])
                    with self.assertRaisesRegex(ValueError, "history diverges"):
                        rehearse(live, bundle, root)
                    self.assertEqual(list(root.glob("stockroom-restore-*")), [])
