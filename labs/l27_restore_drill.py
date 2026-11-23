#!/usr/bin/env python3
"""L27/C24: restore gates on disposable SQLite fixtures only."""
import hashlib
import json
import platform
import sqlite3
import tempfile
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(connection):
    return {
        "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
        "fk": connection.execute("PRAGMA foreign_key_check").fetchall(),
        "schema": connection.execute("PRAGMA user_version").fetchone()[0],
        "balance": connection.execute("SELECT balance FROM account WHERE id=1").fetchone()[0],
        "ledger": connection.execute("SELECT COALESCE(SUM(delta),0) FROM ledger").fetchone()[0],
        "watermark": connection.execute("SELECT value FROM metadata WHERE key='watermark'").fetchone()[0],
    }


def validate(path, expected_hash, expected_watermark):
    require(digest(path) == expected_hash, "digest mismatch")
    with sqlite3.connect(path) as db:
        state = probe(db)
        require(state["integrity"] == "ok", "integrity failure")
        require(not state["fk"], "foreign key failure")
        require(state["schema"] == 1, "incompatible schema")
        require(state["balance"] == state["ledger"], "business invariant failure")
        require(state["watermark"] == expected_watermark, "watermark mismatch")
    return state


def main():
    started = time.monotonic_ns()
    with tempfile.TemporaryDirectory(prefix="sqlite-l27-") as directory:
        root = Path(directory)
        source, backup, restored = (root / name for name in ("source.db", "backup.db", "restored.db"))
        with sqlite3.connect(source) as db:
            version, source_id = db.execute("SELECT sqlite_version(), sqlite_source_id()").fetchone()
            db.executescript("""
                PRAGMA foreign_keys=ON;
                PRAGMA user_version=1;
                CREATE TABLE account(id INTEGER PRIMARY KEY, balance INTEGER NOT NULL);
                CREATE TABLE ledger(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL
                    REFERENCES account(id), delta INTEGER NOT NULL);
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT INTO account VALUES(1,10);
                INSERT INTO ledger VALUES(1,1,10);
                INSERT INTO metadata VALUES('watermark',1);
            """)
            db.commit()
            with sqlite3.connect(backup) as destination:
                db.backup(destination)
        expected_hash = digest(backup)
        backup_state = validate(backup, expected_hash, 1)
        restored.write_bytes(backup.read_bytes())
        restored_state = validate(restored, expected_hash, 1)
        with sqlite3.connect(restored) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO ledger VALUES(2,1,5)")
            db.execute("UPDATE account SET balance=15 WHERE id=1")
            db.execute("UPDATE metadata SET value=2 WHERE key='watermark'")
            db.commit()
            require(probe(db)["watermark"] == 2, "write smoke test failed")
        # Negative 1: wrong digest must fail before opening.
        rejected = {}
        try:
            validate(backup, "0" * 64, 1)
        except RuntimeError as exc:
            rejected["digest"] = str(exc)
        # Negative 2: valid digest of a semantically inconsistent file must fail.
        inconsistent = root / "inconsistent.db"
        inconsistent.write_bytes(backup.read_bytes())
        with sqlite3.connect(inconsistent) as db:
            db.execute("UPDATE account SET balance=99 WHERE id=1")
            db.commit()
        try:
            validate(inconsistent, digest(inconsistent), 1)
        except RuntimeError as exc:
            rejected["semantic"] = str(exc)
        # Negative 3: schema from an unsupported future version.
        future = root / "future.db"
        future.write_bytes(backup.read_bytes())
        with sqlite3.connect(future) as db:
            db.execute("PRAGMA user_version=2")
        try:
            validate(future, digest(future), 1)
        except RuntimeError as exc:
            rejected["schema"] = str(exc)
        require(rejected == {
            "digest": "digest mismatch",
            "semantic": "business invariant failure",
            "schema": "incompatible schema",
        }, "negative gate failed")
        require(digest(backup) == expected_hash, "backup mutated")
        print(json.dumps({
            "lab": "L27", "sqlite_version": version, "sqlite_source_id": source_id,
            "python": platform.python_version(), "platform": platform.platform(),
            "backup": backup_state, "restored": restored_state,
            "smoke_watermark": 2, "negative_rejections": rejected,
            "backup_preserved": True,
            "elapsed_ms": round((time.monotonic_ns()-started)/1e6, 3),
            "limitations": "No production cutover, no crash/power loss, no OS-level durability claim; RTO only local drill duration.",
        }, sort_keys=True))


if __name__ == "__main__":
    main()
