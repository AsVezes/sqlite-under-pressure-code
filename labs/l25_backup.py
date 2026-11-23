"""L25 disposable online backup with coordinated writer and negative candidate."""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def verify(path):
    with sqlite3.connect(path) as con:
        require(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity")
        return (con.execute("SELECT COUNT(*), MAX(id) FROM events").fetchone(),
                con.execute("SELECT value FROM meta WHERE key='watermark'").fetchone()[0])

def main():
    with tempfile.TemporaryDirectory(prefix="l25-backup-") as directory:
        root = Path(directory)
        source, destination, rejected = (root / n for n in
                                          ("source.db", "candidate.db", "rejected.db"))
        with sqlite3.connect(source) as writer:
            require(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal", "WAL")
            writer.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
            writer.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            writer.execute("INSERT INTO meta VALUES('watermark', 1)")
            writer.executemany("INSERT INTO events VALUES(?, zeroblob(3000))",
                               [(i,) for i in range(1, 201)])
            writer.commit()
            before = verify(source)
            require(before == ((200, 200), 1), "initial state")
            progress = []
            fired = [False]
            def callback(status, remaining, total):
                progress.append((status, remaining, total))
                if not fired[0] and remaining > 0:
                    fired[0] = True
                    writer.execute("INSERT INTO events VALUES(201, zeroblob(3000))")
                    writer.execute("UPDATE meta SET value=2 WHERE key='watermark'")
                    writer.commit()
            with sqlite3.connect(source) as reader, sqlite3.connect(destination) as target:
                reader.backup(target, pages=1, progress=callback)
            require(fired[0], "writer not exercised between backup steps")
            observed = verify(destination)
            require(observed in (((200, 200), 1), ((201, 201), 2)), "torn snapshot")
            require(verify(source) == ((201, 201), 2), "source writer commit")
            require(progress and progress[-1][1] == 0, "backup incomplete")
            with sqlite3.connect(rejected) as bad:
                bad.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, payload BLOB NOT NULL)")
                bad.commit()
            failed = False
            try:
                verify(rejected)
            except sqlite3.DatabaseError:
                failed = True
            require(failed, "incomplete candidate passed validation")
            with sqlite3.connect(source) as identity:
                version, source_id = identity.execute(
                    "SELECT sqlite_version(), sqlite_source_id()").fetchone()
            print(json.dumps({
                "lab": "L25", "sqlite_version": version, "sqlite_source_id": source_id,
                "python": platform.python_version(), "platform": platform.platform(),
                "before": before, "source_after": verify(source), "backup": observed,
                "callback_count": len(progress), "writer_during_backup": fired[0],
                "negative_rejected": failed, "filesystem": "not characterized",
                "limits": "No power loss or fault VFS; callback timing is an explicit event, not a durability guarantee."
            }, sort_keys=True))

if __name__ == "__main__":
    main()
