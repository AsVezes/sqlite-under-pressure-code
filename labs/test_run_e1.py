"""Regression tests for the E1 runner's process-supervision contract.

Run: python3 -m unittest discover -s labs -p 'test_run_e1.py' -v
Mocks replace subprocess execution: no database, process or filesystem fault is induced.
"""
import json
import subprocess
import unittest
from unittest.mock import patch

import run_e1

UNITTEST_OK = "----------------------------------------------------------------------\nRan 1 test in 0.001s\n\nOK\n"


class RunnerSupervisionTests(unittest.TestCase):
    def test_e1_manifest_covers_wal_visibility_and_contention(self):
        self.assertEqual(
            run_e1.PILOTS,
            ("l05_atomicity", "l08_rollback_recovery", "l08_spill_controls",
             "l09_wal_views", "l10_checkpoint", "l10_writer_busy", "l11_stale_snapshot"),
        )
        for name in run_e1.PILOTS:
            with self.subTest(lab=name):
                self.assertTrue((run_e1.ROOT / (name + ".py")).is_file())
                self.assertTrue((run_e1.ROOT / ("test_" + name + ".py")).is_file())

    def test_success_requires_both_child_exit_codes_zero(self):
        completed = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr=UNITTEST_OK)
        with patch.object(run_e1.subprocess, "run", return_value=completed) as call:
            result = run_e1.run_one("l05_atomicity")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["commands"]), 2)
        self.assertTrue(all(row["exit_code"] == 0 for row in result["commands"]))
        self.assertEqual(call.call_count, 2)
        for args, kwargs in call.call_args_list:
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(kwargs["timeout"], run_e1.COMMAND_TIMEOUT_SECONDS)
            self.assertEqual(kwargs["cwd"], run_e1.ROOT)

    def test_zero_discovered_tests_is_not_success(self):
        empty = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="----------------------------------------------------------------------\nRan 0 tests in 0.000s\n\nOK\n")
        probe = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr=UNITTEST_OK)
        with patch.object(run_e1.subprocess, "run", side_effect=[empty, probe]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][0]["error"], "missing positive unittest success evidence")

    def test_missing_unittest_summary_is_not_success(self):
        empty = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
        probe = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr="")
        with patch.object(run_e1.subprocess, "run", side_effect=[empty, probe]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][0]["error"], "missing positive unittest success evidence")

    def test_zero_exit_with_failed_unittest_summary_is_rejected(self):
        failed = subprocess.CompletedProcess(
            ["python"], 0, stdout="",
            stderr="Ran 1 test in 0.001s\n\nFAILED (failures=1)\n",
        )
        probe = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {"valid": True},
                               "sqlite_source_id": "test-id", "sqlite_version": "test-version"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[failed, probe]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][0]["error"], "missing positive unittest success evidence")

    def test_nonzero_child_is_not_success(self):
        outcomes = [
            subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK),
            subprocess.CompletedProcess(["python"], 1, stdout="", stderr="failed"),
        ]
        with patch.object(run_e1.subprocess, "run", side_effect=outcomes):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual([x["exit_code"] for x in result["commands"]], [0, 1])

    def test_timeout_keeps_partial_output_and_continues(self):
        timed_out = subprocess.TimeoutExpired(
            cmd=["python"], timeout=120, output=b"partial stdout", stderr=b"partial stderr"
        )
        completed = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr=UNITTEST_OK)
        with patch.object(run_e1.subprocess, "run", side_effect=[timed_out, completed]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["commands"]), 2)
        first = result["commands"][0]
        self.assertEqual(first["error"], "timeout")
        self.assertIsNone(first["exit_code"])
        self.assertEqual(first["stdout"], "partial stdout")
        self.assertEqual(first["stderr"], "partial stderr")

    def test_launch_failure_does_not_abort_next_child(self):
        completed = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr=UNITTEST_OK)
        with patch.object(run_e1.subprocess, "run", side_effect=[OSError("launch refused"), completed]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][0]["error"], "OSError")
        self.assertEqual(len(result["commands"]), 2)


    def test_zero_exit_with_failed_oracle_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        bad = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "fail", "oracles": {"valid": False},
                               "sqlite_source_id": "test-id", "sqlite_version": "test-version"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, bad]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")

    def test_zero_exit_with_unparseable_probe_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        bad = subprocess.CompletedProcess(["python"], 0, stdout="not-json", stderr=UNITTEST_OK)
        with patch.object(run_e1.subprocess, "run", side_effect=[good, bad]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe JSON")


    def test_zero_exit_without_sqlite_identity_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        missing = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {"valid": True},
                               "sqlite_version": "test-version"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, missing]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")

    def test_zero_exit_with_empty_oracles_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        missing = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {},
                               "sqlite_source_id": "test-id", "sqlite_version": "test-version"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, missing]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")

    def test_zero_exit_with_non_boolean_oracle_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        invalid = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {"valid": 1},
                               "sqlite_source_id": "test-id", "sqlite_version": "test-version"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, invalid]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")


    def test_zero_exit_with_non_object_json_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        malformed = subprocess.CompletedProcess(["python"], 0, stdout='["pass"]', stderr=UNITTEST_OK)
        with patch.object(run_e1.subprocess, "run", side_effect=[good, malformed]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe JSON")

    def test_zero_exit_with_nested_empty_identity_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        malformed = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {"valid": True},
                               "environment": {}, "sqlite_version": "outer-version",
                               "sqlite_source_id": "outer-source"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, malformed]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")


    def test_zero_exit_with_numeric_sqlite_identity_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        invalid = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {"valid": True},
                               "sqlite_source_id": 123, "sqlite_version": 3460100}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, invalid]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")

    def test_zero_exit_with_whitespace_sqlite_identity_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr=UNITTEST_OK)
        invalid = subprocess.CompletedProcess(
            ["python"], 0,
            stdout=json.dumps({"status": "pass", "oracles": {"valid": True},
                               "sqlite_source_id": "  ", "sqlite_version": "3.46.1"}),
            stderr="",
        )
        with patch.object(run_e1.subprocess, "run", side_effect=[good, invalid]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe evidence")


if __name__ == "__main__":
    unittest.main()
