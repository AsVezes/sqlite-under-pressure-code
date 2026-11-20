"""Regression oracles for disposable L09 WAL visibility pilot."""
import unittest
from l09_wal_views import experiment


class L09WalViewsTests(unittest.TestCase):
    def test_snapshot_and_control(self):
        result = experiment()
        self.assertEqual("pass", result["status"], result)
        self.assertTrue(all(result["oracles"].values()), result)
        self.assertEqual(
            ["A_READ", "B_COMMIT", "A_RETAINED", "C_READ",
             "A_RENEWED", "B_SECOND_COMMIT", "A_FIRST_READ"],
            [event["ack"] for event in result["events"]],
        )
        self.assertEqual(
            [0, 0, 1, 1, 2],
            [event["value"] for event in result["events"] if "value" in event],
        )
        self.assertTrue(result["sqlite_source_id"])
        self.assertTrue(result["sqlite_version"])

    def test_separate_disposable_runs(self):
        first = experiment()
        second = experiment()
        self.assertEqual("pass", first["status"], first)
        self.assertEqual("pass", second["status"], second)
        self.assertEqual(first["oracles"], second["oracles"])


if __name__ == "__main__":
    unittest.main()
