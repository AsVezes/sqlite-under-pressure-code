#!/usr/bin/env python3
"""Regression gates for the published L26/C23 copy-methods exercise.

Run: python3 -m unittest discover -s labs -p test_l26_copy_methods.py -v
Repeat with python3 -O. Every database is created under TemporaryDirectory.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import l26_copy_methods as lab


SCRIPT = Path(__file__).with_name("l26_copy_methods.py")


class CopyMethodsTests(unittest.TestCase):
    def test_literal_entrypoint_normal_and_optimized(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable]
                if optimized:
                    command.append("-O")
                result = subprocess.run(
                    command + [str(SCRIPT)], capture_output=True, text=True,
                    timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                data = json.loads(result.stdout)
                self.assertTrue(data["sqlite_version"])
                self.assertTrue(data["sqlite_source_id"])
                self.assertEqual(data["source"], [2, 2])
                self.assertEqual(data["main_only"], [1, 1])
                self.assertEqual(
                    data["negative"], "main-only watermark mismatch rejected"
                )
                for name in ("backup", "vacuum", "dump-replay"):
                    with self.subTest(method=name):
                        self.assertEqual(data["copies"][name]["state"], [2, 2])
                        self.assertEqual(len(data["copies"][name]["sha256"]), 64)
                        self.assertGreater(data["copies"][name]["bytes"], 0)
                for elapsed in data["duration_ns"].values():
                    self.assertGreaterEqual(elapsed, 0)

    def test_integrity_gate_rejects_corruption_without_assert(self):
        with tempfile.TemporaryDirectory(prefix="sqlite-l26-test-") as tmp:
            path = Path(tmp) / "broken.db"
            path.write_bytes(bytes(4096))
            with self.assertRaises(Exception):
                lab.inspect(path)

    def test_watermark_gate_rejects_stale_but_valid_copy(self):
        with tempfile.TemporaryDirectory(prefix="sqlite-l26-test-") as tmp:
            data = lab.run(Path(tmp))
            self.assertEqual(data["main_only"], [1, 1])
            self.assertNotEqual(data["main_only"], data["source"])
            self.assertEqual(lab.inspect(Path(tmp) / "main-only.db"), (1, 1))


if __name__ == "__main__":
    unittest.main()
