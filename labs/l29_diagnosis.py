#!/usr/bin/env python3
"""L29/C26-C27: distinguish a held write lock from an inefficient query.

Disposable SQLite fixtures only. Explicit Event handshakes establish order;
elapsed durations are observations, never concurrency-order oracles.
"""
import json
import os
import platform
import sqlite3
import tempfile
import threading
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(connection):
    return {
        "version": connection.execute("SELECT sqlite_version()").fetchone()[0],
        "source_id": connection.execute("SELECT sqlite_source_id()").fetchone()[0],
    }


def lock_case(path):
    owner = sqlite3.connect(path, timeout=0, isolation_level=None, check_same_thread=False)
    contender = sqlite3.connect(path, timeout=0, isolation_level=None, check_same_thread=False)
    acquired = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    failures = []

    def hold_writer():
        try:
            owner.execute("BEGIN IMMEDIATE")
            owner.execute("UPDATE items SET amount = amount + 1 WHERE id = 1")
            acquired.set()  # ACK: write transaction is active
            require(release.wait(10), "watchdog: release not received")
            owner.execute("COMMIT")
        except BaseException as exc:
            failures.append(str(exc))
            if owner.in_transaction:
                owner.execute("ROLLBACK")
        finally:
            acquired.set()
            finished.set()

    worker = threading.Thread(target=hold_writer)
    worker.start()
    try:
        require(acquired.wait(10), "watchdog: writer not ready")
        require(not failures, "writer failed before contention: " + repr(failures))
        start = time.perf_counter_ns()
        try:
            contender.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", None)
            require(code == sqlite3.SQLITE_BUSY, f"expected SQLITE_BUSY=5, got {code}: {exc}")
            blocked_code = code
        else:
            contender.execute("ROLLBACK")
            raise RuntimeError("negative control: second writer unexpectedly acquired lock")
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    finally:
        release.set()  # GO: writer may commit
        require(finished.wait(10), "watchdog: writer did not finish")
        worker.join()
        owner.close()
    require(not failures, "writer failed: " + repr(failures))
    require(contender.execute("SELECT amount FROM items WHERE id=1").fetchone()[0] == 2,
            "committed amount differs")
    contender.execute("BEGIN IMMEDIATE")
    contender.execute("ROLLBACK")  # positive control: lock released
    contender.close()
    return {"negative_busy_code": blocked_code, "busy_elapsed_ms_observed": round(elapsed_ms, 3),
            "positive_lock_released": True, "final_amount": 2}


def plan_case(path):
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, category TEXT NOT NULL, payload TEXT NOT NULL)")
        db.executemany("INSERT INTO events(category,payload) VALUES (?,?)",
                       (("rare" if i % 100 == 0 else "common", "payload-" + str(i))
                        for i in range(1, 10001)))
        db.commit()
        query = "SELECT count(*) FROM events WHERE category = ?"
        before = [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + query, ("rare",))]
        t0 = time.perf_counter_ns()
        baseline = db.execute(query, ("rare",)).fetchone()[0]
        before_ms = (time.perf_counter_ns() - t0) / 1_000_000
        require(baseline == 100, "fixture cardinality incorrect")
        require(any("SCAN events" in detail for detail in before),
                "negative control: expected full scan before index")
        db.execute("CREATE INDEX events_category_idx ON events(category)")
        after = [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + query, ("rare",))]
        t1 = time.perf_counter_ns()
        indexed = db.execute(query, ("rare",)).fetchone()[0]
        after_ms = (time.perf_counter_ns() - t1) / 1_000_000
        require(indexed == baseline, "index changed result")
        require(any("USING COVERING INDEX events_category_idx" in detail for detail in after),
                "positive control: covering index not selected")
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity failed")
        return {"rows": 10000, "matches": indexed, "plan_before": before, "plan_after": after,
                "scan_ms_observed": round(before_ms, 3), "indexed_ms_observed": round(after_ms, 3)}
    finally:
        db.close()


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l29-") as directory:
        path = Path(directory) / "lock.sqlite"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, amount INTEGER NOT NULL)")
        db.execute("INSERT INTO items VALUES(1,1)")
        db.commit()
        engine = identity(db)
        db.close()
        lock = lock_case(path)
        plan = plan_case(Path(directory) / "plan.sqlite")
        print(json.dumps({"lab": "L29", "chapter": "C26-C27", "engine": engine,
                          "environment": {"python": platform.python_version(),
                                          "os": platform.platform(), "cwd": os.getcwd()},
                          "lock": lock, "query": plan,
                          "oracle": "PASS",
                          "limitations": "No multi-host test; timing is illustrative, not an SLA. "
                                         "Architecture decisions require workload and topology evidence."},
                         sort_keys=True))


if __name__ == "__main__":
    main()
