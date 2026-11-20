#!/usr/bin/env python3
"""Run E1 standalone pilots with reproducible raw evidence.

Run from any directory: python3 labs/run_e1.py
All pilots own their disposable SQLite fixtures. This runner never accepts a DB path.
Output is JSON on stdout; redirect to a file outside the repository if retention is needed.
"""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PILOTS = ("l05_atomicity", "l10_writer_busy", "l11_stale_snapshot")
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
            results.append({"argv": argv, "exit_code": process.returncode,
                            "stdout": process.stdout, "stderr": process.stderr})
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
        "commands": results, "ok": all(r["exit_code"] == 0 for r in results)}


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
                  "Execution results are environment-specific; independent review is required",
              ]}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
