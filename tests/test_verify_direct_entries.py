"""Disposable tests for the CP08–CP11 direct-entry verifier.

These fixtures are synthetic; they check the real Git-apply flow and rejection
conditions without claiming any historical snapshot has been executed.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_direct_entries as verifier


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class DirectEntryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="direct-entry-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.snapshot = self.root / "historical"
        self.snapshot.mkdir()
        (self.snapshot / "stockroom").mkdir()
        (self.snapshot / "stockroom" / "ledger.py").write_text("legacy\n", encoding="utf-8")
        (self.snapshot / "stockroom" / "writer.py").write_text("writer\n", encoding="utf-8")
        work = self.root / "build"
        work.mkdir()
        (work / "stockroom").mkdir()
        (work / "stockroom" / "ledger.py").write_text("legacy\n", encoding="utf-8")
        (work / "stockroom" / "writer.py").write_text("writer\n", encoding="utf-8")
        git(work, "init", "-q")
        git(work, "add", "-A")
        self.before = git(work, "write-tree")
        git(work, "-c", "user.name=Offline Test", "-c",
            "user.email=offline@example.invalid", "commit", "-qm", "base")
        (work / "stockroom" / "ledger.py").write_text("atomic\n", encoding="utf-8")
        self.diff = subprocess.run(["git", "diff", "--", "stockroom/ledger.py"],
                                   cwd=work, capture_output=True, text=True,
                                   check=True).stdout
        git(work, "add", "-A")
        self.after_ledger = git(work, "hash-object", "stockroom/ledger.py")
        self.writer_blob = git(work, "hash-object", "stockroom/writer.py")
        self.patches = self.root / "patches"
        self.patches.mkdir()
        (self.patches / "cp08-repair.patch").write_text(self.diff, encoding="utf-8")

    def controlled_verify(self):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(verifier.SNAPSHOT_TREES, {8: self.before}))
            stack.enter_context(patch.dict(verifier.EXPECTED_BLOBS,
                                           {"stockroom/ledger.py": self.after_ledger}))
            stack.enter_context(patch.object(verifier, "EARLY_WRITER", self.writer_blob))
            return verifier.verify(self.snapshot, 8, self.patches, timeout=15)

    def test_valid_repair_is_applied_and_measured(self):
        report = self.controlled_verify()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["archive_tree_observed"], self.before)
        self.assertEqual(report["critical_file_blobs"]["stockroom/ledger.py"],
                         self.after_ledger)
        self.assertEqual((self.snapshot / "stockroom" / "ledger.py").read_text(), "legacy\n")

    def test_modified_repair_is_rejected(self):
        patch_file = self.patches / "cp08-repair.patch"
        original = patch_file.read_text(encoding="utf-8")
        self.assertIn("+atomic", original)
        patch_file.write_text(original.replace("+atomic", "+unsafe"),
                              encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "repair mismatch"):
            self.controlled_verify()

    def test_wrong_historical_snapshot_is_rejected(self):
        (self.snapshot / "stockroom" / "writer.py").write_text("other\n",
                                                              encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "wrong historical source snapshot"):
            self.controlled_verify()

    def test_invalid_checkpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "checkpoint must be"):
            verifier.verify(self.snapshot, 7, self.patches)


if __name__ == "__main__":
    unittest.main()
