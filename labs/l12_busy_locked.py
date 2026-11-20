#!/usr/bin/env python3
"""L12: SQLITE_LOCKED versus SQLITE_BUSY and retry of rollback-journal COMMIT.

No external database path; only disposable fixtures and explicit SQL acknowledgements.
"""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def run():
    events = []
    with tempfile.TemporaryDirectory(prefix="sqlite-l12-") as tmp:
        path = Path(tmp) / "fixture.sqlite3"
        a = sqlite3.connect(path, isolation_level=None, timeout=0)
        b = sqlite3.connect(path, isolation_level=None, timeout=0)
        try:
            mode = a.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            a.execute("CREATE TABLE item(value INTEGER NOT NULL)")
            a.executemany("INSERT INTO item VALUES (?)", [(1,), (2,)])
            cursor = a.execute("SELECT value FROM item ORDER BY value")
            first = cursor.fetchone()[0]
            events.append("A_CURSOR_OPEN_ACK")
            try:
                a.execute("DROP TABLE item")
                locked = None
            except sqlite3.Error as exc:
                locked = {"code": exc.sqlite_errorcode, "name": exc.sqlite_errorname}
            events.append("A_DDL_LOCKED_ACK")
            cursor.close()
            a.execute("DROP TABLE item")
            a.execute("CREATE TABLE item(value INTEGER NOT NULL)")
            a.execute("INSERT INTO item VALUES (1)")
            events.append("A_CURSOR_RELEASED_DDL_SUCCEEDED_ACK")
            b.execute("BEGIN")
            before = b.execute("SELECT value FROM item").fetchone()[0]
            events.append("B_READ_LOCK_ACK")
            a.execute("BEGIN IMMEDIATE")
            a.execute("UPDATE item SET value=2")
            events.append("A_UPDATE_UNCOMMITTED_ACK")
            try:
                a.execute("COMMIT")
                busy = None
            except sqlite3.Error as exc:
                busy = {"code": exc.sqlite_errorcode, "name": exc.sqlite_errorname}
            still_open = a.in_transaction
            events.append("A_COMMIT_BUSY_ACK")
            during = b.execute("SELECT value FROM item").fetchone()[0]
            b.execute("ROLLBACK")
            events.append("B_READ_RELEASED_ACK")
            a.execute("COMMIT")
            events.append("A_COMMIT_RETRY_SUCCEEDED_ACK")
            after = b.execute("SELECT value FROM item").fetchone()[0]
            integrity = a.execute("PRAGMA integrity_check").fetchone()[0]
            identity = a.execute("SELECT sqlite_source_id()").fetchone()[0]
            version = a.execute("SELECT sqlite_version()").fetchone()[0]
            oracles = {
                "cursor_open_first_row": first == 1,
                "same_connection_ddl_locked": locked is not None and locked["code"] == sqlite3.SQLITE_LOCKED,
                "ddl_after_cursor_close": True,
                "reader_saw_old_value": before == during == 1,
                "commit_busy": busy is not None and busy["code"] == sqlite3.SQLITE_BUSY,
                "failed_commit_kept_transaction": still_open,
                "retry_after_reader_release": after == 2 and not a.in_transaction,
                "integrity": integrity == "ok",
            }
            return {
                "status": "pass" if all(oracles.values()) else "fail",
                "environment": {"python": sys.version, "platform": platform.platform(),
                                "sqlite_version": version, "sqlite_source_id": identity,
                                "journal_mode": mode, "busy_timeout_ms": 0},
                "events": events,
                "observed": {"locked": locked, "busy": busy,
                             "transaction_open_after_busy": still_open,
                             "before": before, "during": during, "after": after,
                             "integrity_check": integrity},
                "oracles": oracles,
                "limitations": [
                    "Single process, two file connections; ACKs follow completed SQL calls.",
                    "No sleeps; busy_timeout=0 makes contention immediate.",
                    "No process crash, power-loss, or WAL claim.",
                    "Error codes reflect the loaded SQLite library.",
                ],
            }
        finally:
            if a.in_transaction:
                a.execute("ROLLBACK")
            if b.in_transaction:
                b.execute("ROLLBACK")
            a.close()
            b.close()


def main():
    if len(sys.argv) != 1:
        print("No arguments accepted", file=sys.stderr)
        return 2
    report = run()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
