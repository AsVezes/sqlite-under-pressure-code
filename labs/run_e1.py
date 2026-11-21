#!/usr/bin/env python3
"""Run E1 standalone pilots with reproducible raw evidence (L05/L08/L09/L10-checkpoint/L10-writer/L11).

Run from any directory: python3 labs/run_e1.py
All pilots own their disposable SQLite fixtures. This runner never accepts a DB path.
Output is JSON on stdout; redirect to a file outside the repository if retention is needed.
"""
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PILOTS = ("l05_atomicity", "l08_rollback_recovery", "l08_spill_controls", "l09_wal_views", "l10_checkpoint", "l10_writer_busy", "l11_stale_snapshot")
COMMAND_TIMEOUT_SECONDS = 120


def _decoded(value):
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def run_one(name):
    source = ROOT / (name + ".py")
    test = ROOT / ("test_" + name + ".py")
    if not source.is_file() or not test.is_file():
        return {"lab": name, "error": "missing source or test file", "ok": False}
    commands = (
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT),
         "-p", test.name, "-v"],
        [sys.executable, str(source)],
    )
    results = []
    for argv in commands:
        # No shell, no arbitrary DB path, no inherited working directory.
        try:
            process = subprocess.run(
                argv, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            record = {"argv": argv, "exit_code": process.returncode,
                      "stdout": process.stdout, "stderr": process.stderr}
            if argv == commands[1] and process.returncode == 0:
                try:
                    payload = json.loads(process.stdout)
                    oracles = payload.get("oracles")
                    identity = payload.get("environment", payload)
                    if not isinstance(identity, dict):
                        identity = {}
                    if (payload.get("status") != "pass"
                            or not isinstance(oracles, dict)
                            or not oracles
                            or not all(value is True for value in oracles.values())
                            or not identity.get("sqlite_source_id")
                            or not identity.get("sqlite_version")):
                        record["error"] = "invalid probe evidence"
                        record["ok"] = False
                except (ValueError, TypeError, AttributeError):
                    record["error"] = "invalid probe JSON"
                    record["ok"] = False
            if argv == commands[0] and process.returncode == 0:
                # A zero exit without a positive unittest summary is not proof of discovery.
                summary = re.search(r"(?m)^Ran ([0-9]+) tests? in ", process.stderr)
                if summary is None or int(summary.group(1)) == 0:
                    record["error"] = "no positive unittest discovery summary"
                    record["ok"] = False
            results.append(record)
        except subprocess.TimeoutExpired as exc:
            # Do not report a timed-out or killed child as a successful experiment.
            results.append({"argv": argv, "exit_code": None, "ok": False,
                            "error": "timeout", "timeout_seconds": COMMAND_TIMEOUT_SECONDS,
                            "stdout": _decoded(exc.stdout), "stderr": _decoded(exc.stderr)})
        except OSError as exc:
            results.append({"argv": argv, "exit_code": None, "ok": False,
                            "error": type(exc).__name__, "detail": str(exc),
                            "stdout": "", "stderr": ""})
    return {"lab": name, "sha256": {
        source.name: hashlib.sha256(source.read_bytes()).hexdigest(),
        test.name: hashlib.sha256(test.read_bytes()).hexdigest()},
        "commands": results, "ok": all(r["exit_code"] == 0 and r.get("ok", True) for r in results)}


def main():
    results = [run_one(name) for name in PILOTS]
    report = {"runner": "E1 standalone", "python": sys.version,
              "python_executable": sys.executable, "platform": platform.platform(),
              "cwd": str(ROOT), "results": results,
              "limitations": [
                  "SQLite identity and SOURCE_ID are recorded by each pilot's stdout",
                  "Tests and probes run in separate processes and separate disposable fixtures",
                  "This runner does not prove cross-process concurrency or crash durability",
                  "Each subprocess has a 120-second safety timeout; a timeout is failure, not evidence",
                  "The legacy l10_writer_busy is a writer-contention pilot, not the editorial L10 checkpoint",
                  "L08 spill controls infer spill from main-file hashes, not VFS write traces",
                  "Execution results are environment-specific; independent review is required",
              ]}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
