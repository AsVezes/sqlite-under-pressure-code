"""Regression tests for L08 spill/no-spill/commit controls."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROBE = Path(__file__).with_name("l08_spill_controls.py")

class SpillControlsTests(unittest.TestCase):
    def test_three_controls_and_effective_engine_identity(self):
        run = subprocess.run([sys.executable,str(PROBE)],capture_output=True,
                             text=True,timeout=45,check=False)
        self.assertEqual(run.returncode,0,run.stderr+run.stdout)
        data = json.loads(run.stdout)
        self.assertEqual(data["status"],"pass")
        self.assertEqual(data["lab"],"L08")
        self.assertTrue(data["sqlite_version"])
        self.assertTrue(data["sqlite_source_id"])
        self.assertEqual(len(data["observed"]),3)
        self.assertTrue(all(type(v) is bool and v for v in data["oracles"].values()))

    def test_external_database_path_rejected(self):
        run = subprocess.run([sys.executable,str(PROBE),"/tmp/not-owned.sqlite3"],
                             capture_output=True,text=True,timeout=10,check=False)
        self.assertEqual(run.returncode,2)
        self.assertEqual(run.stdout,"")
        self.assertIn("no arguments",run.stderr)

if __name__ == "__main__":
    unittest.main()
