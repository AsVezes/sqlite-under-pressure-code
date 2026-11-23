#!/usr/bin/env python3
"""L22/C20: process termination is not a power-loss durability test."""
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r"""
import json, sqlite3, sys
db, mode, phase = sys.argv[1:]
con = sqlite3.connect(db, isolation_level=None, timeout=0)
con.execute("PRAGMA journal_mode=" + mode)
con.execute("PRAGMA synchronous=FULL")
con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
con.execute("BEGIN IMMEDIATE")
con.execute("INSERT INTO events VALUES (1, 'committed')")
if phase == "after":
    con.execute("COMMIT")
print(json.dumps({"event": "before_kill", "phase": phase, "in_transaction": con.in_transaction}), flush=True)
# Parent acknowledges the checkpoint and terminates us; no arbitrary delay.
sys.stdin.readline()
raise RuntimeError("parent failed to terminate child")
"""

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def inspect(db):
    with sqlite3.connect(db) as con:
        return {
            "rows": con.execute("SELECT id,value FROM events ORDER BY id").fetchall(),
            "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
            "journal_mode": con.execute("PRAGMA journal_mode").fetchone()[0],
        }

def trial(root, mode, phase):
    db = root / (mode + "_" + phase + ".db")
    # Pre-create schema so before-commit never depends on DDL rollback.
    with sqlite3.connect(db) as con:
        actual = con.execute("PRAGMA journal_mode=" + mode).fetchone()[0]
        require(actual.lower() == mode.lower(), "journal mode refused")
        con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    proc = subprocess.Popen([sys.executable, "-u", "-c", CHILD, str(db), mode, phase],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        line = proc.stdout.readline()
        require(bool(line), "child exited before checkpoint")
        event = json.loads(line)
        require(event == {"event": "before_kill", "phase": phase,
                          "in_transaction": phase == "before"},
                "unexpected child checkpoint: " + line)
        require(proc.poll() is None, "child already exited")
        proc.kill()
        stdout, stderr = proc.communicate(timeout=10)
        require(proc.returncode is not None and proc.returncode != 0,
                "child was not terminated")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    state = inspect(db)
    expected = [] if phase == "before" else [[1, "committed"]]
    require([list(x) for x in state["rows"]] == expected,
            "unexpected committed state: " + repr(state))
    require(state["integrity"] == "ok", "integrity_check failed")
    require(state["journal_mode"].lower() == mode, "journal mode changed")
    return {"mode": mode, "phase": phase, "checkpoint": event,
            "child_returncode": proc.returncode, "child_stderr": stderr,
            "state": state, "oracle": "pass"}

def main():
    with sqlite3.connect(":memory:") as con:
        engine = con.execute("SELECT sqlite_version(), sqlite_source_id()").fetchone()
    with tempfile.TemporaryDirectory(prefix="sqlite-l22-") as d:
        trials = [trial(Path(d), mode, phase)
                  for mode in ("delete", "wal") for phase in ("before", "after")]
    print(json.dumps({"lab": "L22", "chapter": "C20", "python": sys.version,
                      "platform": platform.platform(), "sqlite_version": engine[0],
                      "sqlite_source_id": engine[1], "synchronous": "FULL",
                      "filesystem": "not characterized", "trials": trials,
                      "scope": "process kill only; no OS crash, power loss, or xSync fault"},
                     indent=2, default=str))

if __name__ == "__main__":
    main()
