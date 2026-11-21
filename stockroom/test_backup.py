from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from .backup import capture, digest, latest, verify_bundle
from .environment import connect, initialize_workspace
from .ledger import initialize_ledger
from .migrate import step
from .storage import profile
from .transfer import Transfer
from .writer import install, submit


def ready(root):
    path = Path(initialize_workspace(root)["database"])
    initialize_ledger(path)
    profile(path, "wal")
    install(path)
    step(path, 10)
    step(path, 10)
    return path


class BackupTests(unittest.TestCase):
    def test_backup_under_write_and_interrupted_capture(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            path = ready(root)
            written = []
            def concurrent(_status, left, _total):
                if left > 0 and not written:
                    written.append(submit(path, Transfer("during", "item-bolt",
                                                        "loc-north", "loc-south", 3)))
            result = capture(path, root, progress=concurrent)
            self.assertEqual(len(written), 1)
            good = Path(result["bundle"])
            state, manifest = verify_bundle(good)
            self.assertEqual(state["watermark"], 1)
            with closing(connect(good / "ledger.db", read_only=True)) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone(), ("delete",))
            def fail(*_):
                raise RuntimeError("deliberate backup failure")
            with self.assertRaisesRegex(RuntimeError, "deliberate"):
                capture(path, root, progress=fail)
            self.assertEqual(latest(root, manifest["workspace_id"]), good)
            self.assertEqual(list(root.glob(".stockroom-stage-*")), [])

    def test_receipt_trigger_missing_or_inert_refuses_publication(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            path = ready(root)
            with closing(connect(path)) as db:
                db.execute("DROP TRIGGER record_transfer_receipt")
                with self.assertRaisesRegex(ValueError, "receipt trigger"):
                    capture(path, root)
                db.execute("CREATE TRIGGER record_transfer_receipt AFTER INSERT ON transfer BEGIN SELECT 1; END")
            with self.assertRaisesRegex(ValueError, "receipt trigger"):
                capture(path, root)
            self.assertEqual(list(root.glob("stockroom-backup-*")), [])


    def test_verify_rejects_sidecars_and_wal_mode_without_sidecars(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            path = ready(root)
            bundle = Path(capture(path, root)["bundle"])
            snapshot = bundle / "ledger.db"
            for suffix in ("-journal", "-wal", "-shm"):
                with self.subTest(suffix=suffix):
                    sidecar = snapshot.with_name(snapshot.name + suffix)
                    sidecar.touch()
                    with self.assertRaisesRegex(ValueError, "unexpected SQLite sidecar"):
                        verify_bundle(bundle)
                    sidecar.unlink()
            with closing(connect(snapshot)) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            manifest = bundle / "manifest.json"
            metadata = json.loads(manifest.read_text())
            metadata["sha256"] = digest(snapshot)
            manifest.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "must use DELETE journal mode"):
                verify_bundle(bundle)
