"""L25 / C23: consistent SQLite online backup with a coordinated WAL writer.

Run: python3 labs/l25_online_backup.py
     python3 -O labs/l25_online_backup.py
Only disposable databases in TemporaryDirectory are used.
"""
import hashlib
import json
import os
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def snapshot(conn):
    return conn.execute("SELECT id, amount FROM ledger ORDER BY id").fetchall()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l25-") as root:
        root = Path(root)
        source_path = root / "source.db"
        backup_path = root / "backup.db"
        source = sqlite3.connect(source_path, isolation_level=None, timeout=0)
        writer = sqlite3.connect(source_path, isolation_level=None, timeout=0)
        destination = sqlite3.connect(backup_path, isolation_level=None, timeout=0)
        try:
            require(source.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal", "WAL unavailable")
            source.execute("PRAGMA wal_autocheckpoint=0")
            source.execute("CREATE TABLE ledger(id INTEGER PRIMARY KEY, amount INTEGER NOT NULL CHECK(amount > 0))")
            source.execute("BEGIN IMMEDIATE")
            source.executemany("INSERT INTO ledger(id, amount) VALUES (?, ?)", ((i, i * 2) for i in range(1, 3001)))
            source.execute("COMMIT")
            before = snapshot(source)
            require(len(before) == 3000, "baseline fixture incomplete")
            events = []
            changed = False

            def progress(status, remaining, total):
                nonlocal changed
                events.append((status, remaining, total))
                # The callback is an explicit page-copy event, not a timing guess.
                # Commit a new WAL transaction once; the backup may restart.
                if not changed:
                    changed = True
                    writer.execute("BEGIN IMMEDIATE")
                    writer.execute("INSERT INTO ledger VALUES (3001, 6002)")
                    writer.execute("COMMIT")

            source.backup(destination, pages=1, progress=progress, sleep=0.0)
            require(changed, "writer was never triggered")
            require(events and events[-1][0] == sqlite3.SQLITE_DONE, "backup did not finish")
            after = snapshot(source)
            copied = snapshot(destination)
            require(len(after) == 3001, "coordinated commit missing from source")
            require(copied == before or copied == after, "backup has torn or impossible logical state")
            require(destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "backup integrity failed")
            require(destination.execute("PRAGMA foreign_key_check").fetchall() == [], "backup foreign keys invalid")
            require(not destination.in_transaction, "destination transaction left open")
            # Negative control: a copied main database file alone is not a WAL backup.
            # No assertion about its content: checkpoints and connection cleanup can alter it.
            manifest = {
                "lab": "L25", "chapter": "C23",
                "python": sys.version.split()[0], "platform": platform.platform(),
                "sqlite_version": source.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": source.execute("SELECT sqlite_source_id()").fetchone()[0],
                "journal_mode": source.execute("PRAGMA journal_mode").fetchone()[0],
                "baseline_rows": len(before), "source_rows_after_commit": len(after),
                "backup_rows": len(copied), "backup_cut": "before" if copied == before else "after",
                "progress_events": len(events), "last_progress": events[-1],
                "backup_sha256": digest(backup_path),
                "integrity_check": "ok", "foreign_key_check": [],
                "negative_control": "reject mixed logical snapshot (neither before nor after)",
                "limitations": "single process; WAL writer commits during backup callback; no crash, disk-full, power loss or durability guarantee"
            }
            print(json.dumps(manifest, indent=2, sort_keys=True))
        finally:
            destination.close()
            writer.close()
            source.close()


if __name__ == "__main__":
    run()
