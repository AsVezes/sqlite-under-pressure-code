"""L07 / C06: SQLite constraint conflict actions on a disposable fixture.

Run: python3 labs/l07_conflict_actions.py
Explicit SQL transaction boundaries; no existing database paths accepted.
"""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path


def require(value, message):
    if not value:
        raise RuntimeError("L07 oracle failed: " + message)


def connection(path):
    return sqlite3.connect(path, isolation_level=None)


def run_case(root, algorithm):
    path = root / (algorithm.lower() + ".sqlite3")
    db = connection(path)
    try:
        db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, qty INTEGER NOT NULL UNIQUE)")
        db.executemany("INSERT INTO t VALUES (?, ?)", [(1, 10), (2, 20)])
        db.execute("BEGIN")
        db.execute("INSERT INTO t VALUES (3, 30)")
        # The second VALUES row collides with qty=20. FAIL retains the first
        # row of this statement; ABORT undoes the entire statement only.
        error = None
        try:
            db.execute(
                "INSERT OR " + algorithm + " INTO t(id,qty) "
                "VALUES (4,40),(5,20),(6,60)"
            )
        except sqlite3.IntegrityError as exc:
            error = {"name": getattr(exc, "sqlite_errorname", None),
                     "code": getattr(exc, "sqlite_errorcode", None)}
        active = db.in_transaction
        during = [list(r) for r in db.execute("SELECT id,qty FROM t ORDER BY id")]
        if active:
            db.execute("COMMIT")
        db.close()
        db = connection(path)
        after = [list(r) for r in db.execute("SELECT id,qty FROM t ORDER BY id")]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        expected = {
            "ABORT": [[1,10],[2,20],[3,30]],
            "FAIL": [[1,10],[2,20],[3,30],[4,40]],
            "IGNORE": [[1,10],[2,20],[3,30],[4,40],[6,60]],
            "ROLLBACK": [[1,10],[2,20]],
        }[algorithm]
        checks = {
            "expected_error": (error is None if algorithm == "IGNORE"
                               else error is not None and
                               error["code"] == sqlite3.SQLITE_CONSTRAINT_UNIQUE),
            "transaction_state": active == (algorithm != "ROLLBACK"),
            "state_before_reopen": during == expected,
            "persisted_state": after == expected,
            "integrity": integrity == "ok",
        }
        for name, value in checks.items():
            require(value, algorithm + ":" + name)
        return {"algorithm": algorithm, "error": error, "transaction_active_after_statement": active,
                "before_reopen": during, "after_reopen": after, "oracles": checks}
    finally:
        if db.in_transaction:
            db.execute("ROLLBACK")
        db.close()


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l07-") as directory:
        root = Path(directory)
        cases = [run_case(root, algorithm) for algorithm in
                 ("ABORT", "FAIL", "IGNORE", "ROLLBACK")]
    with sqlite3.connect(":memory:") as probe:
        identity = {
            "sqlite_version": probe.execute("SELECT sqlite_version()").fetchone()[0],
            "sqlite_source_id": probe.execute("SELECT sqlite_source_id()").fetchone()[0],
        }
    return {"lab": "L07", "status": "pass", "environment": {
        "python": platform.python_version(), "os": platform.platform(), **identity},
        "cases": cases, "limitations": [
            "UNIQUE constraint only; FK violations do not honor all OR actions",
            "REPLACE and UPSERT have different semantics and are not tested here",
            "single connection per case; no concurrency, process failure, or power-loss proof",
            "SQLite stdlib engine identity, not sqlite3 CLI identity",
        ]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
