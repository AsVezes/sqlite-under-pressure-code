#!/usr/bin/env python3
"""L09: WAL snapshot visibility, on a disposable database (stdlib only).

No external database path is accepted. Program-order ACKs follow completed SQL
calls; they do not attempt to prove concurrent scheduling.
"""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def experiment():
    events = []
    with tempfile.TemporaryDirectory(prefix="sqlite-l09-") as tmp:
        db = Path(tmp) / "snapshot.sqlite3"
        anchor = sqlite3.connect(db, isolation_level=None, timeout=0)
        a = b = c = None
        try:
            mode = anchor.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            anchor.execute("PRAGMA wal_autocheckpoint=0")
            anchor.execute("CREATE TABLE counter(value INTEGER NOT NULL)")
            anchor.execute("INSERT INTO counter VALUES (0)")
            a = sqlite3.connect(db, isolation_level=None, timeout=0)
            b = sqlite3.connect(db, isolation_level=None, timeout=0)
            c = sqlite3.connect(db, isolation_level=None, timeout=0)
            b.execute("PRAGMA wal_autocheckpoint=0")
            a.execute("BEGIN")
            old = a.execute("SELECT value FROM counter").fetchone()[0]
            events.append({"ack": "A_READ", "value": old})
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE counter SET value=1")
            b.execute("COMMIT")
            events.append({"ack": "B_COMMIT"})
            retained = a.execute("SELECT value FROM counter").fetchone()[0]
            events.append({"ack": "A_RETAINED", "value": retained})
            c.execute("BEGIN")
            fresh = c.execute("SELECT value FROM counter").fetchone()[0]
            events.append({"ack": "C_READ", "value": fresh})
            c.execute("COMMIT")
            wal_exists = Path(str(db) + "-wal").exists()
            a.execute("COMMIT")
            a.execute("BEGIN")
            renewed = a.execute("SELECT value FROM counter").fetchone()[0]
            events.append({"ack": "A_RENEWED", "value": renewed})
            a.execute("COMMIT")
            # Control: BEGIN alone does not establish a read snapshot.
            a.execute("BEGIN")
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE counter SET value=2")
            b.execute("COMMIT")
            events.append({"ack": "B_SECOND_COMMIT"})
            no_prior_read = a.execute("SELECT value FROM counter").fetchone()[0]
            events.append({"ack": "A_FIRST_READ", "value": no_prior_read})
            a.execute("COMMIT")
            checks = {
                "wal_enabled": mode.lower() == "wal",
                "old_snapshot_retained": old == 0 and retained == 0,
                "new_reader_sees_commit": fresh == 1,
                "renewed_reader_sees_commit": renewed == 1,
                "begin_without_read_not_pinned": no_prior_read == 2,
                "wal_present_while_anchor_open": wal_exists,
            }
            return {
                "lab": "L09",
                "status": "pass" if all(checks.values()) else "fail",
                "sqlite_version": anchor.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": anchor.execute("SELECT sqlite_source_id()").fetchone()[0],
                "compile_options": [r[0] for r in anchor.execute("PRAGMA compile_options")],
                "python": sys.version,
                "platform": platform.platform(),
                "journal_mode": mode,
                "events": events,
                "oracles": checks,
                "limitations": [
                    "Single-process, sequential ACK experiment; not a scheduling test",
                    "WAL file presence is contextual, not a visibility oracle",
                    "No durability, crash, or checkpoint-completion claim",
                ],
            }
        finally:
            for connection in (a, b, c, anchor):
                if connection is not None:
                    connection.close()


if __name__ == "__main__":
    result = experiment()
    print(json.dumps(result, indent=2, sort_keys=True))
    sys.exit(0 if result["status"] == "pass" else 1)
