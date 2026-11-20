"""Re-run the full L01 probe in a disposable workspace."""
import importlib.util
from pathlib import Path
import unittest


LAB = Path(__file__).resolve().parents[1] / "labs" / "l01_identity.py"
spec = importlib.util.spec_from_file_location("l01_identity", LAB)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class L01IdentityTests(unittest.TestCase):
    def test_all_observed_oracles(self):
        result = module.run_probe()
        self.assertEqual(result["status"], "pass", result)
        self.assertTrue(all(result["oracles"].values()), result["oracles"])
        self.assertTrue(result["environment"]["python_sqlite_source_id"])

    def test_no_acceptance_of_external_database_path(self):
        # No path argument exists: the probe always makes its own TemporaryDirectory.
        import inspect
        self.assertEqual(list(inspect.signature(module.run_probe).parameters), [])


if __name__ == "__main__":
    unittest.main()
