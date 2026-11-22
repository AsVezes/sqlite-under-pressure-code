"""L19/C17: disposable index write-cost and space-maintenance experiment.

Run: python3 labs/l19_index_cost.py
No benchmark threshold: timings are observations, not a universal speed claim.
"""
import json
import os
import platform
import sqlite3
import tempfile
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(db):
    return {
        "sqlite_version": db.execute("select sqlite_version()").fetchone()[0],
        "sqlite_source_id": db.execute("select sqlite_source_id()").fetchone()[0],
        "compile_options": [r[0] for r in db.execute("pragma compile_options")],
    }


def snapshot(db):
    return db.execute("select id, category, amount from entries order by id").fetchall()


def stats(db, path):
    return {
        "page_count": db.execute("pragma page_count").fetchone()[0],
        "freelist_count": db.execute("pragma freelist_count").fetchone()[0],
        "bytes": path.stat().st_size,
    }


def workload(path, indexed):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        require(db.execute("pragma journal_mode=DELETE").fetchone()[0] == "delete", "journal mode")
        db.execute("pragma synchronous=FULL")
        db.execute("pragma auto_vacuum=NONE")
        db.execute("create table entries(id integer primary key, category integer not null, amount integer not null)")
        if indexed:
            db.execute("create index entries_category_amount on entries(category, amount)")
        before = stats(db, path)
        timings = {}
        for phase, statements in (
            ("insert", [("insert into entries values(?,?,?)", (i, i % 17, i % 101)) for i in range(1, 3001)]),
            ("update", [("update entries set amount=amount+1 where id=?", (i,)) for i in range(1, 3001, 2)]),
            ("delete", [("delete from entries where id=?", (i,)) for i in range(1, 3001, 3)]),
        ):
            start = time.perf_counter_ns()
            db.execute("begin immediate")
            try:
                for sql, params in statements:
                    db.execute(sql, params)
                db.execute("commit")
            except BaseException:
                db.execute("rollback")
                raise
            timings[phase] = time.perf_counter_ns() - start
        after = stats(db, path)
        rows = snapshot(db)
        require(len(rows) == 2000, "deleted row count")
        require(db.execute("pragma integrity_check").fetchone()[0] == "ok", "integrity")
        require(after["freelist_count"] > 0, "expected free pages after deletion")
        return {"identity": identity(db), "before": before, "after": after,
                "timings_ns": timings, "rows": rows}
    finally:
        db.close()


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l19-") as tmp:
        root = Path(tmp)
        plain = workload(root / "plain.db", False)
        indexed = workload(root / "indexed.db", True)
        require(plain["rows"] == indexed["rows"], "O2 result mismatch")
        require(indexed["after"]["bytes"] > plain["after"]["bytes"], "index footprint control")
        db = sqlite3.connect(root / "indexed.db", isolation_level=None)
        try:
            old = snapshot(db)
            old_stats = stats(db, root / "indexed.db")
            db.execute("vacuum")
            new_stats = stats(db, root / "indexed.db")
            require(snapshot(db) == old, "VACUUM changed rows")
            require(db.execute("pragma integrity_check").fetchone()[0] == "ok", "post-VACUUM integrity")
            require(new_stats["freelist_count"] == 0, "VACUUM did not clear freelist")
            require(new_stats["bytes"] <= old_stats["bytes"], "VACUUM grew database")
            # Negative control: deliberately corrupt the expected result, not the DB.
            try:
                require(snapshot(db) == old[:-1], "NEGATIVE_CONTROL_DETECTED")
            except RuntimeError as exc:
                require(str(exc) == "NEGATIVE_CONTROL_DETECTED", "wrong negative failure")
            else:
                raise RuntimeError("negative control escaped")
        finally:
            db.close()
        report = {
            "lab": "L19", "chapter": "C17",
            "environment": {"python": platform.python_version(), "os": platform.platform(),
                            "filesystem": "local temporary directory", "journal": "DELETE", "synchronous": "FULL"},
            "sqlite": indexed["identity"], "seed": "id=1..3000; category=id%17; amount=id%101",
            "operations": {"insert": 3000, "update": 1500, "delete": 1000},
            "plain": {k: v for k, v in plain.items() if k not in ("rows", "identity")},
            "indexed": {k: v for k, v in indexed.items() if k not in ("rows", "identity")},
            "vacuum_before": old_stats, "vacuum_after": new_stats,
            "oracles": {"O2_equal_rows": True, "O5_index_footprint": True,
                        "integrity": True, "negative_control_detected": True},
            "limitations": "Single process; wall-clock noise; no WAL frames, crash, fsync tracing or universal performance ranking.",
        }
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
