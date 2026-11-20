from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .drill import drill
from .environment import initialize_workspace, inspect_workspace
from .ledger import check_ledger, initialize_ledger
from .writer import install


class DrillTests(unittest.TestCase):
    def test_old_ledger_reconciled_on_copy_after_combined_incident(self):
        with TemporaryDirectory() as directory:
            path = Path(initialize_workspace(Path(directory))["database"])
            initialize_ledger(path)
            install(path)
            before = check_ledger(path)
            result = drill(path)
            self.assertEqual(result["schema_start"], 1)
            self.assertEqual(result["migration"][-1]["schema"], 2)
            self.assertEqual(result["rpo_operations"], 1)
            self.assertEqual(result["final_watermark"], result["restored_cut"] + 1)
            self.assertIn("begin_failed", [e["phase"] for e in result["contention"]])
            self.assertEqual(result["profile"]["journal"], "wal")
            self.assertEqual(inspect_workspace(path)["schema_version"], 1)
            self.assertEqual(check_ledger(path), before)
