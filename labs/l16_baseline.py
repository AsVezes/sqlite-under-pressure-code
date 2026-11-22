"""L16/C14: comparable query baseline on a disposable F2-like fixture.

Run: python3 labs/l16_baseline.py
No speedup assertion: timing is an observation, not a SQLite guarantee.
"""
import json
import os
import platform
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fixture(conn, count=12000):
    conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, item INTEGER NOT NULL, qty INTEGER NOT NULL)")
    conn.executemany(
        "INSERT INTO events(id,item,qty) VALUES(?,?,?)",
        ((i, 1 if i % 5 else 2 + (i % 99), 1 + (i % 7)) for i in range(1, count + 1)),
    )
    conn.commit()


def sample(conn, item, repeats=9, warmups=2):
    sql = "SELECT count(*), coalesce(sum(qty),0) FROM events WHERE item=?"
    plan = [list(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql, (item,))]
    for _ in range(warmups):
        conn.execute(sql, (item,)).fetchone()
    values, durations = [], []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        values.append(conn.execute(sql, (item,)).fetchone())
        durations.append(time.perf_counter_ns() - start)
    require(all(v == values[0] for v in values), "unstable query result")
    return {"parameter": item, "result": list(values[0]), "plan": plan,
            "duration_ns": durations, "median_ns": statistics.median(durations)}


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l16-") as root:
        path = Path(root) / "f2.sqlite"
        conn = sqlite3.connect(path)
        try:
            fixture(conn)
            a = sample(conn, 1)
            a_repeat = sample(conn, 1)
            b = sample(conn, 2)
            # Positive: A/A equality and independent SQL aggregate oracle.
            expected_a = conn.execute("SELECT count(*),sum(qty) FROM events WHERE item=1").fetchone()
            require(tuple(a["result"]) == expected_a, "A oracle mismatch")
            require(a["result"] == a_repeat["result"], "A/A result drift")
            expected_b = conn.execute("SELECT count(*),sum(qty) FROM events WHERE item=2").fetchone()
            require(tuple(b["result"]) == expected_b, "B oracle mismatch")
            # Negative: using A's result for B must be detected by the oracle.
            negative_detected = a["result"] != b["result"]
            require(negative_detected, "negative control did not detect parameter substitution")
            require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity failure")
            result = {
                "lab": "L16", "status": "pass", "sqlite_version": conn.execute("select sqlite_version()").fetchone()[0],
                "sqlite_source_id": conn.execute("select sqlite_source_id()").fetchone()[0],
                "python": platform.python_version(), "os": platform.platform(),
                "filesystem": "local temporary directory (type not verified)",
                "database": "discarded temporary fixture", "rows": 12000,
                "distribution": "item=1 for 4/5 rows; remaining 1/5 distributed across items 2..100",
                "cache_size": conn.execute("PRAGMA cache_size").fetchone()[0],
                "warmups": 2, "repeats": 9, "unit": "nanoseconds",
                "setup_in_timing": False, "a": a, "a_repeat": a_repeat, "b": b,
                "positive_oracles": True, "negative_detected": negative_detected,
                "limitations": "Python execute+fetch time, not isolated prepare time; no filesystem cache control; plans and timings environment-specific; no speedup claim",
            }
            print(json.dumps(result, sort_keys=True))
            return result
        finally:
            conn.close()


if __name__ == "__main__":
    run()
