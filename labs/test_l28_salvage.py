"""Check that the canonical L28 distinguishes a verified backup from salvage."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


CLI = shutil.which("sqlite3")
LAB = Path(__file__).with_name("l28_salvage.py")


@unittest.skipUnless(CLI, "SQLite CLI is unavailable")
class SalvageTests(unittest.TestCase):
    def test_restore_and_salvage_have_distinct_evidence(self):
        capability = subprocess.run([CLI, ":memory:", ".help recover"],
                                    text=True, capture_output=True, check=False, timeout=10)
        if capability.returncode or ".recover" not in capability.stdout:
            self.skipTest("SQLite CLI .recover capability is unavailable")
        for flags in ([], ["-O"]):
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, *flags, str(LAB)],
                                        text=True, capture_output=True, check=False, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                evidence = json.loads(result.stdout)
                self.assertEqual(evidence["verified_restore_count"], 20)
                self.assertNotEqual(evidence["damaged_read"],
                                    {"readable_rows": 20, "integrity": "ok"})
                self.assertEqual(evidence["recovery_exit"], 0)
                self.assertEqual(evidence["import_exit"], 0)
                self.assertEqual(evidence["quarantine_integrity"], "ok")
                self.assertEqual(evidence["quarantine_fk"], [])
                self.assertIs(evidence["promoted"], False)
