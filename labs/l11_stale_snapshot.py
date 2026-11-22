#!/usr/bin/env python3
"""L11: stale WAL snapshot promotion with explicit phase acknowledgements.

Run: python3 labs/l11_stale_snapshot.py
Only newly-created TemporaryDirectory databases are touched.
"""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def connect(path):
    if sys.version_info >= (3, 12):
        return sqlite3.connect(path, autocommit=True, timeout=0)
    return sqlite3.connect(path, isolation_level=None, timeout=0)


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l11-") as directory:
        path = Path(directory) / "fixture.sqlite3"
        anchor = connect(path)
        a = connect(path)
        b = connect(path)
        events = []
        try:
            journal = anchor.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if journal != "wal":
                raise RuntimeError("WAL unavailable: " + journal)
            anchor.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
            anchor.execute("INSERT INTO counter VALUES (1, 0)")
            identity = {
                "sqlite_version": anchor.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": anchor.execute("SELECT sqlite_source_id()").fetchone()[0],
                "compile_options": [r[0] for r in anchor.execute("PRAGMA compile_options")],
                "journal_mode": journal,
            }
            # A establishes an actual read snapshot before B writes.
            a.execute("BEGIN")
            first = a.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]
            events.append({"phase": "A_READ_ACK", "value": first})
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE counter SET n=n+1 WHERE id=1")
            b.execute("COMMIT")
            events.append({"phase": "B_COMMIT_ACK"})
            # The active snapshot cannot be promoted after B commits.
            error = None
            try:
                a.execute("UPDATE counter SET n=n+1 WHERE id=1")
            except sqlite3.OperationalError as exc:
                error = {
                    "code": getattr(exc, "sqlite_errorcode", None),
                    "name": getattr(exc, "sqlite_errorname", None),
                    "message": str(exc),
                }
            events.append({"phase": "A_PROMOTION_ACK", "error": error})
            old_view = a.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]
            a.execute("ROLLBACK")
            events.append({"phase": "A_ROLLBACK_ACK"})
            a.execute("BEGIN")
            fresh_view = a.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]
            a.execute("UPDATE counter SET n=n+1 WHERE id=1")
            a.execute("COMMIT")
            events.append({"phase": "A_FRESH_COMMIT_ACK"})
            final = b.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]
            # Control: BEGIN without a read does not establish an old snapshot.
            a.execute("BEGIN")
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE counter SET n=n+1 WHERE id=1")
            b.execute("COMMIT")
            events.append({"phase": "B_CONTROL_COMMIT_ACK"})
            a.execute("UPDATE counter SET n=n+1 WHERE id=1")
            a.execute("COMMIT")
            control_final = anchor.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]
            extended = getattr(sqlite3, "SQLITE_BUSY_SNAPSHOT", 517)
            oracles = {
                "initial_snapshot_zero": first == 0,
                "extended_busy_snapshot": (error is not None
                    and error["code"] == extended
                    and error["name"] == "SQLITE_BUSY_SNAPSHOT"
                    and (error["code"] & 255) == sqlite3.SQLITE_BUSY),
                "old_snapshot_still_visible": old_view == 0,
                "fresh_snapshot_sees_b": fresh_view == 1,
                "fresh_commit_applies_once": final == 2,
                "unread_begin_can_write": control_final == 4,
            }
            return {
                "lab": "L11",
                "status": "pass" if all(oracles.values()) else "fail",
                "environment": {"python": sys.version, "platform": platform.platform(), **identity},
                "events": events,
                "observations": {"old_view": old_view, "fresh_view": fresh_view,
                                 "final": final, "control_final": control_final},
                "oracles": oracles,
                "limitations": [
                    "Deterministic single-process sequential ACK protocol; not a simultaneous-process stress test",
                    "No sleeps or timeout-based ordering evidence",
                    "Only WAL snapshot promotion; not durability or power-loss testing",
                ],
            }
        finally:
            a.close()
            b.close()
            anchor.close()


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)
