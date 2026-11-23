#!/usr/bin/env python3
"""L21/C19: resumable migration with a committed progress cursor.

Standalone disposable pilot. No Stockroom dependency or destructive external paths.
"""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def migrate(conn, batch_size=3, fail_after_batch=False):
    """Each batch and its cursor commit atomically; replay is idempotent."""
    require(batch_size > 0, "batch_size must be positive")
    while True:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                "SELECT last_id FROM migration_progress WHERE name='v2'"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT id, quantity FROM legacy WHERE id>? ORDER BY id LIMIT ?",
                (cursor, batch_size),
            ).fetchall()
            for item_id, quantity in rows:
                conn.execute(
                    "INSERT INTO ledger(item_id, quantity) VALUES (?, ?) "
                    "ON CONFLICT(item_id) DO UPDATE SET quantity=excluded.quantity",
                    (item_id, quantity),
                )
            if rows:
                conn.execute(
                    "UPDATE migration_progress SET last_id=? WHERE name='v2'",
                    (rows[-1][0],),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        if not rows:
            return
        if fail_after_batch:
            raise InterruptedError("injected interruption after committed batch")


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l21-") as tmp:
        path = Path(tmp) / "migration.db"
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            version, source_id = conn.execute(
                "SELECT sqlite_version(), sqlite_source_id()"
            ).fetchone()
            conn.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE legacy(id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL);
                CREATE TABLE ledger(item_id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL);
                CREATE TABLE migration_progress(
                    name TEXT PRIMARY KEY, last_id INTEGER NOT NULL
                );
                INSERT INTO migration_progress VALUES ('v2',0);
            """)
            conn.executemany(
                "INSERT INTO legacy VALUES (?,?)",
                [(i, i * 7) for i in range(1, 11)],
            )
            interrupted = False
            try:
                migrate(conn, fail_after_batch=True)
            except InterruptedError as exc:
                interrupted = str(exc) == "injected interruption after committed batch"
            require(interrupted, "negative interruption control did not fire")
            cursor = conn.execute(
                "SELECT last_id FROM migration_progress WHERE name='v2'"
            ).fetchone()[0]
            require(cursor == 3, "first batch/cursor not committed together")
            require(conn.execute("SELECT count(*) FROM ledger").fetchone()[0] == 3,
                    "partial batch mismatch")
            conn.close()
            conn = sqlite3.connect(path, isolation_level=None)
            migrate(conn)
            expected = conn.execute(
                "SELECT id,quantity FROM legacy ORDER BY id"
            ).fetchall()
            actual = conn.execute(
                "SELECT item_id,quantity FROM ledger ORDER BY item_id"
            ).fetchall()
            require(expected == actual and len(actual) == 10,
                    "resume lost or duplicated data")
            require(conn.execute(
                "SELECT last_id FROM migration_progress WHERE name='v2'"
            ).fetchone()[0] == 10, "cursor did not reach final row")
            migrate(conn)
            require(conn.execute("SELECT count(*) FROM ledger").fetchone()[0] == 10,
                    "replay duplicated rows")
            # Adversarial negative: cursor advanced without corresponding row.
            conn.execute("DELETE FROM ledger WHERE item_id=4")
            corrupt = conn.execute(
                "SELECT id,quantity FROM legacy EXCEPT "
                "SELECT item_id,quantity FROM ledger"
            ).fetchall()
            require(corrupt == [(4, 28)], "semantic negative control was not detected")
            conn.execute("INSERT INTO ledger VALUES (4,28)")
            require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                    "structural integrity failure")
            require(conn.execute(
                "SELECT count(*) FROM (SELECT id,quantity FROM legacy EXCEPT "
                "SELECT item_id,quantity FROM ledger)"
            ).fetchone()[0] == 0, "semantic integrity failure")
            print(json.dumps({
                "lab": "L21", "chapter": "C19", "status": "passed",
                "sqlite_version": version, "sqlite_source_id": source_id,
                "python": sys.version.split()[0], "platform": platform.platform(),
                "fixture": "TemporaryDirectory", "first_committed_cursor": cursor,
                "final_rows": len(actual), "negative_missing_row_detected": True,
                "limits": [
                    "simulated interruption only after commit, not power loss",
                    "single-process batches; no concurrent writer test",
                    "no application schema-version compatibility gate",
                    "filesystem type not independently verified"
                ]
            }, sort_keys=True))
        finally:
            conn.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(json.dumps({"lab": "L21", "status": "failed",
                          "error": type(exc).__name__ + ": " + str(exc)}),
              file=sys.stderr)
        sys.exit(1)
