from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .environment import initialize_workspace
from .ledger import initialize_ledger
from .report import measure
from .transfer import Transfer
from .writer import install, submit


class ReportTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(initialize_workspace(Path(temp.name))["database"])
        initialize_ledger(self.path)
        install(self.path)
        for key, item, src, dst in [
            ("z", "item-bolt", "loc-north", "loc-south"),
            ("a", "item-bolt", "loc-north", "loc-south"),
            ("other", "item-nut", "loc-south", "loc-north"),
        ]:
            submit(self.path, Transfer(key, item, src, dst, 1))

    def test_filter_and_tie_break_are_stable(self):
        report = measure(self.path, "item-bolt", 3)
        self.assertEqual([row[0] for row in report["rows"]], ["a", "z"])
        self.assertEqual([row[-1] for row in report["rows"]], [2, 1])
        self.assertEqual(report["sha256"], measure(self.path, "item-bolt")["sha256"])
        self.assertEqual(measure(self.path, "missing")["rows"], [])
        self.assertEqual(len(report["samples_ns"]), 3)

    def test_compare_uses_separate_copies_for_read_write_cost(self):
        from .tune import compare
        from .ledger import check_ledger
        before = check_ledger(self.path)
        result = compare(self.path, 2)
        for plain, indexed in zip(result["plain"]["reports"], result["indexed"]["reports"]):
            self.assertEqual(plain["sha256"], indexed["sha256"])
        self.assertEqual(len(result["indexed"]["write_samples_ns"]), 8)
        self.assertEqual(check_ledger(self.path), before)
