#!/usr/bin/env python3
"""Regression tests for L05; execute: python3 -m unittest discover -s labs -p 'test_l05_*.py' -v.

All SQLite databases are created in a fresh TemporaryDirectory. No path input.
"""
import tempfile
import unittest
from pathlib import Path

import l05_atomicity as lab


class L05AtomicityTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="sqlite-l05-tests-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def test_five_scenarios_and_reopened_state(self):
        cases = {
            name: lab.run_case(self.root, name, name)
            for name in (
                "statement_failure", "transaction_failure", "success",
                "savepoint_outer_rollback", "insufficient"
            )
        }
        baseline = {"balances": [[1, 10], [2, 0]], "ledger": []}
        partial = {"balances": [[1, 7], [2, 0]], "ledger": []}
        committed = {
            "balances": [[1, 7], [2, 3]],
            "ledger": [[1, 2, 3]],
        }
        for name in cases:
            self.assertEqual(cases[name]["before"], baseline, name)
            self.assertEqual(cases[name]["integrity_check"], "ok", name)
        self.assertEqual(cases["statement_failure"]["after"], partial)
        self.assertEqual(cases["transaction_failure"]["after"], baseline)
        self.assertEqual(cases["success"]["after"], committed)
        self.assertEqual(cases["savepoint_outer_rollback"]["after"], baseline)
        self.assertEqual(cases["insufficient"]["after"], baseline)

    def test_negative_control_partial_transfer_is_detected(self):
        observed = lab.run_case(self.root, "negative", "statement_failure")
        # A balance-only conservation check MUST reject the intentionally
        # interrupted transfer; PRAGMA integrity_check alone will not.
        before = sum(qty for _, qty in observed["before"]["balances"])
        after = sum(qty for _, qty in observed["after"]["balances"])
        self.assertNotEqual(after, before)
        self.assertEqual(observed["integrity_check"], "ok")

    def test_no_database_path_argument_in_main(self):
        # The lab entry point accepts no database path and creates its own root.
        # Verify the externally visible entry point without changing CWD.
        import contextlib
        import io
        import json
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = lab.main()
        self.assertEqual(status, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["lab"], "L05")
        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(report["oracles"].values()))
        self.assertTrue(report["environment"]["sqlite_source_id"])


if __name__ == "__main__":
    unittest.main()
