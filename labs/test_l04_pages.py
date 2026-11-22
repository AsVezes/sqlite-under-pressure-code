"""Regression checks for L04 physical-layout probe.

Run: python3 -m unittest labs/test_l04_pages.py -v
Uses only disposable databases created by l04_pages.run().
"""
import unittest

try:
    from labs import l04_pages
except ModuleNotFoundError:
    import l04_pages


class L04PageLayoutTests(unittest.TestCase):
    def test_both_layouts_and_negative_control(self):
        report = l04_pages.run()
        self.assertEqual(report["lab"], "L04")
        self.assertEqual(report["status"], "pass", report)
        for name, passed in report["checks"].items():
            self.assertTrue(passed, name)
        self.assertTrue(report["checks"]["negative_control_detected"])
        self.assertEqual(set(report["measurements"]), {"rowid", "without_rowid"})
        for layout in report["measurements"].values():
            self.assertEqual(layout["page_size"], 4096)
            self.assertEqual(layout["auto_vacuum"], 0)
            self.assertEqual(layout["integrity"], "ok")
            self.assertEqual(layout["bytes_before"], layout["bytes_after"])
            self.assertGreaterEqual(layout["pages_before"], 1)
            self.assertGreaterEqual(layout["freelist_after"], 0)
        self.assertTrue(report["environment"]["sqlite_source_id"])


if __name__ == "__main__":
    unittest.main()
