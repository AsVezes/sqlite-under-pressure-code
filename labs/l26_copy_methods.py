#!/usr/bin/env python3
"""L26 / C23: compare supported copies with an intentionally stale WAL main file.

Only disposable databases are used. This is a controlled single-process pilot,
not a filesystem snapshot or durability/power-loss certification.
"""
import hashlib
import json
import platform
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def inspect(path):
    db = sqlite3.connect(path)
    try:
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity")
        return (db.execute("SELECT count(*) FROM receipts").fetchone()[0],
                db.execute("SELECT max(id) FROM receipts").fetchone()[0])
    finally:
        db.close()


def run(root):
    source = root / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE receipts(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO receipts VALUES(1, 'baseline')")
    anchor = sqlite3.connect(source, isolation_level=None)
    try:
        require(anchor.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal", "WAL unavailable")
        anchor.execute("PRAGMA wal_autocheckpoint=0")
        writer = sqlite3.connect(source, isolation_level=None)
        try:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO receipts VALUES(2, 'committed-in-wal')")
            writer.execute("COMMIT")
            require((root / "source.db-wal").exists(), "WAL missing")
            require(inspect(source) == (2, 2), "source receipt")
            # Negative control: raw main-only copy is NOT a valid online backup.
            main_only = root / "main-only.db"
            shutil.copyfile(source, main_only)
            stale = inspect(main_only)
            require(stale == (1, 1), "main-only unexpectedly includes WAL commit")

            backup = root / "backup.db"
            started = time.perf_counter_ns()
            dest = sqlite3.connect(backup)
            try:
                anchor.backup(dest)
            finally:
                dest.close()
            backup_ns = time.perf_counter_ns() - started

            vacuum = root / "vacuum.db"
            started = time.perf_counter_ns()
            anchor.execute("VACUUM INTO ?", (str(vacuum),))
            vacuum_ns = time.perf_counter_ns() - started

            logical = root / "logical.sql"
            started = time.perf_counter_ns()
            logical.write_text("\n".join(anchor.iterdump()) + "\n", encoding="utf-8")
            dump_ns = time.perf_counter_ns() - started
            replay = root / "replay.db"
            with sqlite3.connect(replay) as db:
                db.executescript(logical.read_text(encoding="utf-8"))
            for name, path in (("backup", backup), ("vacuum", vacuum), ("dump-replay", replay)):
                require(inspect(path) == (2, 2), name + " receipt mismatch")
            # Adversarial oracle: the main-only artifact must fail the expected watermark.
            try:
                require(inspect(main_only) == (2, 2), "watermark mismatch")
            except RuntimeError as exc:
                require(str(exc) == "watermark mismatch", "wrong negative cause")
            else:
                raise RuntimeError("negative control was accepted")
            return {
                "sqlite_version": anchor.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": anchor.execute("SELECT sqlite_source_id()").fetchone()[0],
                "python": platform.python_version(), "platform": platform.platform(),
                "source": [2, 2], "main_only": list(stale),
                "copies": {name: {"state": list(inspect(path)), "bytes": path.stat().st_size,
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                           for name, path in (("backup", backup), ("vacuum", vacuum),
                                              ("dump-replay", replay))},
                "duration_ns": {"backup": backup_ns, "vacuum": vacuum_ns, "dump": dump_ns},
                "negative": "main-only watermark mismatch rejected",
                "limits": "single process; tiny fixture; no fsync guarantee for VACUUM INTO output; no crash, volume snapshot or throughput claim",
            }
        finally:
            writer.close()
    finally:
        anchor.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sqlite-l26-") as tmp:
        print(json.dumps(run(Path(tmp)), indent=2, sort_keys=True))
