#!/usr/bin/env python3
"""L23/C21: disposable SQLITE_FULL page budget and URI read-only controls."""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def capacity(root):
    path = root / "capacity.db"
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA page_size=1024")
        db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
        initial = db.execute("PRAGMA page_count").fetchone()[0]
        limit = initial + 12
        require(db.execute(f"PRAGMA max_page_count={limit}").fetchone()[0] == limit,
                "page limit refused")
        db.execute("BEGIN IMMEDIATE")
        error = None
        for attempt in range(100):
            try:
                db.execute("INSERT INTO records VALUES (?,zeroblob(900))", (attempt + 1,))
            except sqlite3.DatabaseError as exc:
                error = {"code": getattr(exc, "sqlite_errorcode", None),
                         "name": getattr(exc, "sqlite_errorname", None),
                         "message": str(exc)}
                break
        require(error is not None and error["code"] == sqlite3.SQLITE_FULL,
                "expected SQLITE_FULL: " + repr(error))
        # SQLITE_FULL can automatically roll back the transaction.
        if db.in_transaction:
            db.execute("ROLLBACK")
        require(db.execute("PRAGMA page_count").fetchone()[0] <= limit,
                "page budget exceeded")
    finally:
        db.close()
    with sqlite3.connect(path) as verify:
        count = verify.execute("SELECT count(*) FROM records").fetchone()[0]
        integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
        pages = verify.execute("PRAGMA page_count").fetchone()[0]
    require(count == 0 and integrity == "ok" and pages <= limit,
            "failed transaction leaked rows or damaged fixture")
    return {"error": error, "attempts": attempt + 1, "page_limit": limit,
            "pages_after_reopen": pages, "rows_after_reopen": count,
            "integrity": integrity, "oracle": True}


def readonly(root):
    path = root / "readonly.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO records VALUES (1)")
    # URI mode=ro works regardless of POSIX permissions or root privileges.
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                         isolation_level=None) as db:
        before = db.execute("SELECT count(*) FROM records").fetchone()[0]
        try:
            db.execute("INSERT INTO records VALUES (2)")
        except sqlite3.DatabaseError as exc:
            error = {"code": getattr(exc, "sqlite_errorcode", None),
                     "name": getattr(exc, "sqlite_errorname", None),
                     "message": str(exc)}
        else:
            raise RuntimeError("read-only write unexpectedly succeeded")
    with sqlite3.connect(path) as db:
        after = db.execute("SELECT count(*) FROM records").fetchone()[0]
    require(before == after == 1 and error["code"] == sqlite3.SQLITE_READONLY,
            "read-only negative failed: " + repr(error))
    return {"error": error, "rows_before": before, "rows_after": after,
            "oracle": True}


def main():
    with sqlite3.connect(":memory:") as db:
        version, source_id = db.execute(
            "SELECT sqlite_version(),sqlite_source_id()").fetchone()
    with tempfile.TemporaryDirectory(prefix="sqlite-l23-") as tmp:
        a, b = capacity(Path(tmp)), readonly(Path(tmp))
    print(json.dumps({
        "lab": "L23", "chapter": "C21", "status": "pass",
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "sqlite_version": version, "sqlite_source_id": source_id,
                        "filesystem": "not characterized"},
        "oracles": {"capacity": a["oracle"], "readonly": b["oracle"]},
        "capacity": a, "readonly": b,
        "limitations": ["page limit is not physical disk exhaustion",
                        "URI mode=ro is not an injected xWrite/xSync failure",
                        "no power loss or VFS fault injection"]}, indent=2))


if __name__ == "__main__":
    main()
