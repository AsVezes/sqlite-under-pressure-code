"""CP10: a corrupted copied database must be rejected before selection."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from .backup import capture, validate
from .restore import rehearse
from .test_backup import ready


class RestoreCopyIntegrityTests(unittest.TestCase):
    def test_modified_copy_fails_digest_and_removes_staging(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            before = validate(live)
            bundle = Path(capture(live, root)["bundle"])
            from . import restore as restore_module
            real_copy = restore_module.shutil.copyfile

            def corrupt_copy(source, destination):
                result = real_copy(source, destination)
                with Path(destination).open("ab") as stream:
                    stream.write(b"corrupted-copy")
                return result

            with patch("stockroom.restore.shutil.copyfile", side_effect=corrupt_copy) as copied:
                with self.assertRaisesRegex(ValueError, "restored bytes differ"):
                    rehearse(live, bundle, root)

            copied.assert_called_once()
            self.assertEqual(list(root.glob("stockroom-restore-*")), [])
            self.assertEqual(list(root.rglob("selection.json")), [])
            self.assertEqual(validate(live), before)
