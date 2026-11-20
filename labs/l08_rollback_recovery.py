"""L08: rollback journal after terminating an owned disposable worker."""
import json
import platform
import selectors
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

WORKER = """
import sqlite3,sys
c=sqlite3.connect(sys.argv[1], isolation_level=None)
assert c.execute('PRAGMA journal_mode=DELETE').fetchone()[0]=='delete'
c.execute('BEGIN IMMEDIATE')
c.execute('UPDATE items SET qty=999 WHERE id=1')
assert c.execute('SELECT qty FROM items WHERE id=1').fetchone()[0]==999
print('READY',flush=True)
sys.stdin.buffer.read(1)
"""


def main():
    if len(sys.argv) != 1:
        print("L08 accepts no arguments or external database paths", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="sqlite-l08-") as tmp:
        root = Path(tmp).resolve()
        db = root / "fixture.sqlite3"
        with sqlite3.connect(db) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, qty INTEGER NOT NULL)")
            conn.execute("INSERT INTO items VALUES(1, 10)")
        child = subprocess.Popen(
            [sys.executable, "-c", WORKER, str(db)], cwd=root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        try:
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=10):
                raise RuntimeError("worker READY timeout")
            ack = child.stdout.readline().strip()
            if ack != "READY":
                raise RuntimeError("unexpected worker ACK: " + repr(ack))
            journal = root / "fixture.sqlite3-journal"
            before = journal.exists()
            child.kill()  # Only the PID created by this process, after READY.
            child.communicate(timeout=10)
            after = journal.exists()
            with sqlite3.connect(db) as conn:
                qty = conn.execute("SELECT qty FROM items WHERE id=1").fetchone()[0]
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                source_id = conn.execute("SELECT sqlite_source_id()").fetchone()[0]
            oracles = {
                "ready_after_uncommitted_update": ack == "READY",
                "journal_during_transaction": before,
                "journal_after_termination": after,
                "original_value_after_reopen": qty == 10,
                "integrity_check_ok": integrity == "ok",
            }
            result = {
                "lab": "L08",
                "status": "pass" if all(oracles.values()) else "fail",
                "sqlite_version": sqlite3.sqlite_version,
                "sqlite_source_id": source_id,
                "python": sys.version,
                "platform": platform.platform(),
                "commands": ["python3 labs/l08_rollback_recovery.py"],
                "inputs": {"initial_qty": 10, "uncommitted_qty": 999, "journal_mode": "DELETE"},
                "events": ["committed initial row", "child BEGIN IMMEDIATE and UPDATE",
                           "child READY", "parent journal inspection",
                           "parent kills owned child", "parent reopens fixture"],
                "observed": {"qty_after_reopen": qty, "journal_before_kill": before,
                             "journal_after_kill": after, "integrity_check": integrity},
                "oracles": oracles,
                "limitations": [
                    "Process termination, not power loss or filesystem durability",
                    "Journal existence alone does not establish hot-journal status",
                    "Filesystem and sync guarantees not independently verified",
                    "Only disposable database and owned child process are affected",
                ],
            }
            print(json.dumps(result, indent=2))
            return 0 if all(oracles.values()) else 1
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
