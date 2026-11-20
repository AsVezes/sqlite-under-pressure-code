"""Regression tests for the E1 runner's process-supervision contract.

Run: python3 -m unittest discover -s labs -p 'test_run_e1.py' -v
Mocks replace subprocess execution: no database, process or filesystem fault is induced.
"""
import json
import subprocess
import unittest
from unittest.mock import patch

import run_e1


class RunnerSupervisionTests(unittest.TestCase):
    def test_e1_manifest_covers_wal_visibility_and_contention(self):
        self.assertEqual(
            run_e1.PILOTS,
            ("l05_atomicity", "l09_wal_views", "l10_checkpoint", "l10_writer_busy", "l11_stale_snapshot"),
        )
        for name in run_e1.PILOTS:
            with self.subTest(lab=name):
                self.assertTrue((run_e1.ROOT / (name + ".py")).is_file())
                self.assertTrue((run_e1.ROOT / ("test_" + name + ".py")).is_file())

    def test_success_requires_both_child_exit_codes_zero(self):
        completed = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr="")
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

    def test_nonzero_child_is_not_success(self):
        outcomes = [
            subprocess.CompletedProcess(["python"], 0, stdout="", stderr=""),
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
        completed = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr="")
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
        completed = subprocess.CompletedProcess(["python"], 0, stdout=json.dumps({"status": "pass", "oracles": {"valid": True}, "sqlite_source_id": "test-id", "sqlite_version": "test-version"}), stderr="")
        with patch.object(run_e1.subprocess, "run", side_effect=[OSError("launch refused"), completed]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][0]["error"], "OSError")
        self.assertEqual(len(result["commands"]), 2)


    def test_zero_exit_with_failed_oracle_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
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
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
        bad = subprocess.CompletedProcess(["python"], 0, stdout="not-json", stderr="")
        with patch.object(run_e1.subprocess, "run", side_effect=[good, bad]):
            result = run_e1.run_one("l05_atomicity")
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"][1]["error"], "invalid probe JSON")


    def test_zero_exit_without_sqlite_identity_is_rejected(self):
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
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
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
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
        good = subprocess.CompletedProcess(["python"], 0, stdout="", stderr="")
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


if __name__ == "__main__":
    unittest.main()
