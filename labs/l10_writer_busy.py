#!/usr/bin/env python3
"""L10 pilot: distinguish writer contention from stale WAL snapshots.

Run: python3 labs/l10_writer_busy.py
All databases are disposable. Sequential ACKs establish the order; no sleeps.
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


def error_info(exc):
    return {
        "code": getattr(exc, "sqlite_errorcode", None),
        "name": getattr(exc, "sqlite_errorname", None),
        "message": str(exc),
    }


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l10-") as directory:
        path = Path(directory) / "writer.sqlite3"
        a = connect(path)
        b = connect(path)
        events = []
        try:
            mode = a.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise RuntimeError("WAL unavailable: " + mode)
            a.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER NOT NULL)")
            a.execute("INSERT INTO counter VALUES (1, 0)")
            identity = {
                "sqlite_version": a.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": a.execute("SELECT sqlite_source_id()").fetchone()[0],
                "compile_options": [row[0] for row in a.execute("PRAGMA compile_options")],
                "journal_mode": mode,
            }
            a.execute("BEGIN IMMEDIATE")
            a.execute("UPDATE counter SET n=n+1 WHERE id=1")
            events.append({"phase": "A_WRITE_ACK"})
            # B has not acquired a snapshot. Its immediate write request competes
            # with A's active writer transaction, rather than a stale read.
            busy = None
            try:
                b.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                busy = error_info(exc)
            events.append({"phase": "B_BUSY_ACK", "error": busy})
            b_active_after_error = b.in_transaction
            a.execute("COMMIT")
            events.append({"phase": "A_COMMIT_ACK"})
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE counter SET n=n+1 WHERE id=1")
            b.execute("COMMIT")
            events.append({"phase": "B_RETRY_COMMIT_ACK"})
            final = a.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]
            integrity = a.execute("PRAGMA integrity_check").fetchone()[0]
            oracles = {
                "writer_contention_is_busy": busy is not None and busy["code"] == sqlite3.SQLITE_BUSY,
                "busy_did_not_start_transaction": not b_active_after_error,
                "first_commit_visible": final == 2,
                "retry_committed_once": final == 2,
                "structural_integrity": integrity == "ok",
                "ack_sequence": [e["phase"] for e in events] == [
                    "A_WRITE_ACK", "B_BUSY_ACK", "A_COMMIT_ACK", "B_RETRY_COMMIT_ACK"
                ],
            }
            return {
                "lab": "L10",
                "status": "pass" if all(oracles.values()) else "fail",
                "environment": {"python": sys.version, "platform": platform.platform(), **identity},
                "events": events,
                "observations": {"b_in_transaction_after_busy": b_active_after_error,
                                 "final_counter": final, "integrity_check": integrity},
                "oracles": oracles,
                "limitations": [
                    "Single-process, two-connection sequential protocol; not scheduling stress",
                    "timeout=0 makes immediate BUSY observable; no timed retry/backoff measured",
                    "No crash, durability, cross-process, or filesystem fault claims",
                ],
            }
        finally:
            if a.in_transaction:
                a.execute("ROLLBACK")
            if b.in_transaction:
                b.execute("ROLLBACK")
            b.close()
            a.close()


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 1)
