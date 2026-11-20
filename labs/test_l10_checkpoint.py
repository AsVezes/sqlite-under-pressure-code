"""Regression checks for L10 WAL checkpoint, using only disposable fixtures."""
import unittest
from l10_checkpoint import experiment


class L10CheckpointTests(unittest.TestCase):
    def test_checkpoint_is_incomplete_until_reader_releases(self):
        result = experiment()
        self.assertEqual(result["status"], "pass", result)
        self.assertTrue(all(value is True for value in result["oracles"].values()), result)
        self.assertTrue(result["sqlite_source_id"])
        self.assertTrue(result["sqlite_version"])
        self.assertEqual([e["ack"] for e in result["events"]], [
            "A_READ", "B_COMMIT", "PASSIVE_DONE", "READS_DONE",
            "A_RELEASE", "TRUNCATE_DONE"])
        self.assertLess(result["events"][2]["result"][2],
                        result["events"][2]["result"][1])
        self.assertEqual(result["events"][-1]["result"], [0, 0, 0])

    def test_fresh_disposable_run(self):
        first, second = experiment(), experiment()
        self.assertEqual(first["status"], "pass", first)
        self.assertEqual(second["status"], "pass", second)


if __name__ == "__main__":
    unittest.main()
