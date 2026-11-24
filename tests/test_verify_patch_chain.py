"""Offline verifier regression tests: use disposable, synthetic Git trees.

These tests require only Python and Git. They never download a repository, run
a real Stockroom database, or claim CP00–CP11 have passed.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from tools.verify_patch_chain import verify


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


class VerifyPatchChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="verify-cp-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.starter = self.root / "starter"
        self.starter.mkdir()
        self.patches = self.root / "patches"
        self.patches.mkdir()
        self.manifest = self.patches / "trees.json"
        (self.starter / "README.md").write_text("original\n", encoding="utf-8")
        workspace = self.root / "build"
        workspace.mkdir()
        (workspace / "README.md").write_text("original\n", encoding="utf-8")
        git(workspace, "init", "-q")
        git(workspace, "add", "-A")
        before = git(workspace, "write-tree")
        git(workspace, "-c", "user.name=Offline Test", "-c",
            "user.email=offline@example.invalid", "commit", "-qm", "base")
        (workspace / "README.md").write_text("revised\n", encoding="utf-8")
        patch = subprocess.run(["git", "diff", "--", "README.md"], cwd=workspace,
                               capture_output=True, text=True, check=True).stdout
        (self.patches / "cp00.patch").write_text(patch, encoding="utf-8")
        git(workspace, "add", "-A")
        after = git(workspace, "write-tree")
        self.manifest.write_text(json.dumps([{
            "checkpoint": 0, "input_tree": before, "output_tree": after
        }]), encoding="utf-8")
        self.before = before
        self.after = after

    def test_applies_real_git_patch_and_checks_measured_tree(self):
        report = verify(self.starter, self.patches, self.manifest, timeout=15)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["initial_tree"], self.before)
        self.assertEqual(report["checkpoints"][0]["output_tree"], self.after)
        self.assertEqual((self.starter / "README.md").read_text(), "original\n")

    def test_content_mutation_is_rejected_by_measured_tree(self):
        patch = self.patches / "cp00.patch"
        source = patch.read_text(encoding="utf-8")
        self.assertIn("+revised", source)
        patch.write_text(source.replace("+revised", "+malicious"), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "CP00 output mismatch"):
            verify(self.starter, self.patches, self.manifest, timeout=15)
        self.assertEqual((self.starter / "README.md").read_text(), "original\n")

    def test_wrong_starting_tree_fails_before_apply(self):
        (self.starter / "README.md").write_text("wrong\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "wrong starter"):
            verify(self.starter, self.patches, self.manifest, timeout=15)

    def test_refuses_to_overwrite_evidence_directory(self):
        logs = self.root / "previous-evidence"
        logs.mkdir()
        (logs / "sentinel").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be empty"):
            verify(self.starter, self.patches, self.manifest, timeout=15,
                   log_dir=logs)
        self.assertEqual((logs / "sentinel").read_text(), "keep")

    def test_rejects_symlink_inside_starter(self):
        link = self.starter / "external"
        try:
            link.symlink_to(self.root / "not-here")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        with self.assertRaisesRegex(ValueError, "contains a symlink"):
            verify(self.starter, self.patches, self.manifest, timeout=15)


if __name__ == "__main__":
    unittest.main()
