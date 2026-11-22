"""L06 regression and falsification controls (run with and without -O)."""
import unittest
from unittest.mock import patch
import l06_transactions as lab


class L06Tests(unittest.TestCase):
    def test_both_modes(self):
        report = lab.run()
        self.assertEqual(report["status"], "pass")
        self.assertEqual([r["mode"] for r in report["results"]], ["DEFERRED", "IMMEDIATE"])
        self.assertTrue(all(all(r["checks"].values()) for r in report["results"]))
        self.assertTrue(report["environment"]["sqlite_source_id"])
        self.assertTrue(all(r["checks"]["transactions_closed"] for r in report["results"]))

    def test_quantities_and_primary_busy_codes(self):
        report = lab.run()
        self.assertEqual([r["quantity"] for r in report["results"]], [11, 13])
        for result in report["results"]:
            self.assertEqual(result["conflict"]["code"], lab.sqlite3.SQLITE_BUSY)
            self.assertEqual(result["conflict"]["name"], "SQLITE_BUSY")

    def test_unsupported_mode_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "unsupported mode"):
            lab.scenario("EXCLUSIVE")

    def test_negative_control(self):
        with self.assertRaisesRegex(RuntimeError, "oracle failed"):
            lab.require(False, "deliberate false condition")

    def test_wrong_error_code_fails_closed(self):
        with patch.object(lab.sqlite3, "SQLITE_BUSY", -999):
            with self.assertRaisesRegex(RuntimeError, "busy_code"):
                lab.scenario("IMMEDIATE")


if __name__ == "__main__":
    unittest.main()
