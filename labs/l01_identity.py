"""L01: two sessions, two paths — disposable SQLite identity probe.

Run with: python3 labs/l01_identity.py
Requires only the CPython standard library. Does not accept external DB paths.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory


_CHILD = r'''
import json, os, sqlite3
from pathlib import Path
with sqlite3.connect("main db.sqlite3") as con:
    tables = [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    db_path = con.execute("PRAGMA database_list").fetchone()[2]
print(json.dumps({"cwd": os.getcwd(), "database_path": db_path,
                  "tables": tables, "file_exists": Path(db_path).is_file()}))
'''


def _cli_probe() -> dict:
    executable = shutil.which("sqlite3")
    if executable is None:
        return {"status": "unavailable", "reason": "sqlite3 executable absent from PATH"}
    try:
        version = subprocess.run(
            [executable, "-version"], check=True, capture_output=True,
            text=True, timeout=10,
        )
        identity = subprocess.run(
            [executable, ":memory:",
             "SELECT sqlite_version(), sqlite_source_id();"],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"status": "probe_failed", "executable": executable,
                "error": str(exc)}
    return {"status": "available", "executable": executable,
            "version_output": version.stdout.strip(),
            "identity_output": identity.stdout.strip()}


def run_probe() -> dict:
    """Run all destructive operations ONLY in a fresh TemporaryDirectory."""
    started_at = datetime.now(timezone.utc).isoformat()
    with TemporaryDirectory(prefix="sqlite-under-pressure-l01-") as tmp:
        root = Path(tmp).resolve(strict=True)
        work = root / "workspace with spaces"
        different = root / "other working directory"
        work.mkdir()
        different.mkdir()
        sentinel = root / ".owned-by-l01"
        sentinel.write_text("disposable test fixture\n", encoding="utf-8")
        db = work / "main db.sqlite3"
        with closing(sqlite3.connect(db)) as first:
            first.execute("CREATE TABLE marker (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            first.execute("INSERT INTO marker VALUES (?, ?)", ("identity", "same file"))
            first.commit()

        with closing(sqlite3.connect(db)) as a, closing(sqlite3.connect(db)) as b:
            a_row = a.execute("SELECT value FROM marker WHERE name=?", ("identity",)).fetchone()
            b_row = b.execute("SELECT value FROM marker WHERE name=?", ("identity",)).fetchone()
            a_location = a.execute("PRAGMA database_list").fetchone()[2]
            b_location = b.execute("PRAGMA database_list").fetchone()[2]
            journal = a.execute("PRAGMA journal_mode").fetchone()[0]
            source_id = a.execute("SELECT sqlite_source_id()").fetchone()[0]
            compile_options = [row[0] for row in a.execute("PRAGMA compile_options")]

        child = subprocess.run(
            [sys.executable, "-c", _CHILD], cwd=different, check=True,
            capture_output=True, text=True, timeout=15,
        )
        relative = json.loads(child.stdout)

        with closing(sqlite3.connect(":memory:")) as memory_a, closing(
            sqlite3.connect(":memory:")) as memory_b:
            memory_a.execute("CREATE TABLE marker (value TEXT NOT NULL)")
            memory_a.execute("INSERT INTO marker VALUES ('private memory')")
            memory_a_count = memory_a.execute("SELECT COUNT(*) FROM marker").fetchone()[0]
            memory_b_tables = [r[0] for r in memory_b.execute(
                "SELECT name FROM sqlite_master WHERE name='marker'")]

        absent = root / "read-only absent.sqlite3"
        ro_error = None
        try:
            with closing(sqlite3.connect(f"{absent.as_uri()}?mode=ro", uri=True)):
                pass
        except sqlite3.Error as exc:
            ro_error = {"class": type(exc).__name__, "message": str(exc),
                        "sqlite_errorcode": getattr(exc, "sqlite_errorcode", None),
                        "sqlite_errorname": getattr(exc, "sqlite_errorname", None)}

        oracles = {
            "two_connections_one_file": (
                a_row == b_row == ("same file",)
                and Path(a_location).resolve() == db
                and Path(b_location).resolve() == db),
            "relative_path_is_separate": (
                Path(relative["database_path"]).resolve() != db
                and relative["tables"] == [] and relative["file_exists"]),
            "memory_connections_are_private": (
                memory_a_count == 1 and memory_b_tables == []),
            "read_only_absent_does_not_create": (
                ro_error is not None and not absent.exists()),
            "workspace_is_exclusive": sentinel.is_file(),
        }
        result = {
            "lab_id": "L01", "status": "pass" if all(oracles.values()) else "fail",
            "observed_at_utc": started_at,
            "environment": {
                "platform": platform.platform(), "architecture": platform.machine(),
                "python": sys.version, "python_executable": sys.executable,
                "python_sqlite_version": sqlite3.sqlite_version,
                "python_sqlite_version_info": sqlite3.sqlite_version_info,
                "python_sqlite_source_id": source_id,
                "python_sqlite_compile_options": compile_options,
                "filesystem": "not identified by this probe",
                "cli": _cli_probe(),
            },
            "observations": {
                "absolute_path": str(db), "connection_A_path": a_location,
                "connection_B_path": b_location, "connection_A_row": a_row,
                "connection_B_row": b_row, "journal_mode": journal,
                "relative_other_cwd": relative,
                "memory_A_count": memory_a_count,
                "memory_B_tables": memory_b_tables,
                "missing_readonly_error": ro_error,
                "missing_readonly_created_file": absent.exists(),
            },
            "oracles": oracles,
            "limits": [
                "A single local process and a short child process are tested; no network FS claims.",
                "CLI identity is only measured if sqlite3 is available on PATH.",
                "Process interruption, power loss, WAL and checkpoints are not tested in L01.",
                "TemporaryDirectory deletes the entire exclusive fixture after probes return.",
            ],
        }
    return result


def main() -> int:
    result = run_probe()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
