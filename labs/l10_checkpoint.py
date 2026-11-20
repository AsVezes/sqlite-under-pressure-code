#!/usr/bin/env python3
"""L10 checkpoint pilot: pinned WAL reader, PASSIVE and TRUNCATE (disposable)."""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def experiment():
    events = []
    with tempfile.TemporaryDirectory(prefix="sqlite-l10-checkpoint-") as root:
        db = Path(root) / "checkpoint.sqlite3"
        a = sqlite3.connect(db, isolation_level=None, timeout=0)
        b = c = None
        try:
            mode = a.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            a.execute("PRAGMA wal_autocheckpoint=0")
            a.execute("CREATE TABLE t(v INTEGER NOT NULL)")
            a.execute("INSERT INTO t VALUES (0)")
            b = sqlite3.connect(db, isolation_level=None, timeout=0)
            c = sqlite3.connect(db, isolation_level=None, timeout=0)
            b.execute("PRAGMA wal_autocheckpoint=0")
            c.execute("PRAGMA wal_autocheckpoint=0")
            # A reader must actually read to establish its snapshot.
            a.execute("BEGIN")
            before = a.execute("SELECT v FROM t").fetchone()[0]
            events.append({"ack": "A_READ", "value": before})
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE t SET v=1")
            b.execute("COMMIT")
            events.append({"ack": "B_COMMIT"})
            passive = c.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            events.append({"ack": "PASSIVE_DONE", "result": list(passive)})
            retained = a.execute("SELECT v FROM t").fetchone()[0]
            fresh = c.execute("SELECT v FROM t").fetchone()[0]
            events.append({"ack": "READS_DONE", "old": retained, "fresh": fresh})
            a.execute("COMMIT")
            events.append({"ack": "A_RELEASE"})
            truncated = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            events.append({"ack": "TRUNCATE_DONE", "result": list(truncated)})
            checks = {
                "wal_enabled": mode.lower() == "wal",
                "snapshot_pinned": before == 0 and retained == 0 and fresh == 1,
                "passive_report_valid": len(passive) == 3 and passive[0] == 0 and passive[1] >= 1,
                "passive_incomplete": passive[2] < passive[1],
                "truncate_completed": tuple(truncated) == (0, 0, 0),
                "ordered_acks": [e["ack"] for e in events] == [
                    "A_READ", "B_COMMIT", "PASSIVE_DONE", "READS_DONE",
                    "A_RELEASE", "TRUNCATE_DONE"],
            }
            return {
                "lab": "L10-checkpoint",
                "status": "pass" if all(checks.values()) else "fail",
                "sqlite_version": a.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": a.execute("SELECT sqlite_source_id()").fetchone()[0],
                "compile_options": [r[0] for r in a.execute("PRAGMA compile_options")],
                "python": sys.version, "platform": platform.platform(),
                "journal_mode": mode, "events": events, "oracles": checks,
                "limitations": [
                    "Sequential ACKs prove call order, not concurrent scheduling",
                    "PASSIVE may backfill earlier frames; only incomplete progress is asserted",
                    "TRUNCATE completion does not prove crash durability",
                    "Uses an isolated disposable database; no external database paths accepted",
                ],
            }
        finally:
            for conn in (b, c, a):
                if conn is not None:
                    conn.close()


if __name__ == "__main__":
    result = experiment()
    print(json.dumps(result, indent=2, sort_keys=True))
    sys.exit(0 if result["status"] == "pass" else 1)
