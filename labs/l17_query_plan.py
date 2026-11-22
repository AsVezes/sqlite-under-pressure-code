"""L17/C15: inspect query plans before and after an index on a disposable fixture.

Run: python3 labs/l17_query_plan.py
Plan details are observations for the effective SQLite build, not a stable text API.
"""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def plan(conn, sql, args):
    return [list(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql, args)]


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l17-") as root:
        conn = sqlite3.connect(Path(root) / "plan.sqlite")
        try:
            conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, item INTEGER NOT NULL, qty INTEGER NOT NULL)")
            conn.executemany(
                "INSERT INTO events(id,item,qty) VALUES(?,?,?)",
                ((i, i % 101, i % 7 + 1) for i in range(1, 12001)),
            )
            conn.commit()
            sql = "SELECT id,qty FROM events WHERE item=? ORDER BY id"
            parameter = (17,)
            before = plan(conn, sql, parameter)
            before_rows = conn.execute(sql, parameter).fetchall()
            # Negative control: a different predicate must not pass the result oracle.
            wrong_rows = conn.execute(sql, (18,)).fetchall()
            negative_detected = before_rows != wrong_rows
            require(negative_detected, "negative control failed: wrong parameter accepted")
            require(len(before_rows) > 0, "empty positive fixture")
            require(all(row[0] % 101 == 17 for row in before_rows), "incorrect fixture result")
            conn.execute("CREATE INDEX idx_events_item ON events(item)")
            conn.execute("ANALYZE")
            after = plan(conn, sql, parameter)
            after_rows = conn.execute(sql, parameter).fetchall()
            require(before_rows == after_rows, "index changed query result")
            require(any("idx_events_item" in str(row[3]) for row in after),
                    "expected index absent from observed plan")
            require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                    "integrity_check failed")
            result = {
                "lab": "L17", "status": "pass",
                "sqlite_version": conn.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": conn.execute("SELECT sqlite_source_id()").fetchone()[0],
                "python": platform.python_version(), "os": platform.platform(),
                "filesystem": "temporary directory; filesystem type not verified",
                "fixture": "12000 deterministic rows; disposable",
                "query": sql, "parameters": list(parameter),
                "before_plan": before, "after_plan": after,
                "row_count": len(after_rows), "positive_oracles": True,
                "negative_detected": negative_detected,
                "limitations": "EQP detail strings and index choice are planner/version/statistics dependent; no timing or speedup claim",
            }
            print(json.dumps(result, sort_keys=True))
            return result
        finally:
            conn.close()


if __name__ == "__main__":
    run()
