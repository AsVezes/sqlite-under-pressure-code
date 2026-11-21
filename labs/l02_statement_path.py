#!/usr/bin/env python3
"""L02: statement parameters, EXPLAIN and cursor lifetime; disposable fixture only."""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path

def run():
    events = []
    with tempfile.TemporaryDirectory(prefix="sqlite-l02-") as root:
        db = Path(root) / "statement fixture.sqlite3"
        con = sqlite3.connect(db)
        try:
            con.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
            con.executemany("INSERT INTO sample(id,label) VALUES (?,?)", [(1,"O'Brien"),(2,"second")])
            con.commit()
            sql = "SELECT id,label FROM sample WHERE id=? AND label=?"
            plan = con.execute("EXPLAIN " + sql, (1,"O'Brien")).fetchall()
            schema = con.execute("SELECT name,rootpage FROM sqlite_schema WHERE name='sample'").fetchone()
            events.append("SCHEMA_AND_EXPLAIN_ACK")
            cursor = con.cursor()
            first = cursor.execute(sql, (1,"O'Brien")).fetchall()
            events.append("FIRST_BIND_AND_FETCH_ACK")
            second = cursor.execute(sql, (2,"second")).fetchall()
            events.append("SECOND_BIND_AND_FETCH_ACK")
            quoted = cursor.execute(sql, (1,"O'Brien' OR 1=1 --")).fetchall()
            events.append("QUOTE_PAYLOAD_BOUND_ACK")
            numeric_text = cursor.execute(sql, ("1","O'Brien")).fetchall()
            events.append("NUMERIC_TEXT_BIND_ACK")
            try:
                cursor.execute(sql, (1,))
            except sqlite3.ProgrammingError as exc:
                wrong_bind = type(exc).__name__
            else:
                wrong_bind = None
            events.append("NEGATIVE_BIND_COUNT_ACK")
            cursor.close()
            events.append("CURSOR_CLOSED_ACK")
            reusable = con.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
            with sqlite3.connect(db) as observer:
                persistent = observer.execute("SELECT id,label FROM sample ORDER BY id").fetchall()
                integrity = observer.execute("PRAGMA integrity_check").fetchone()[0]
            oracles = {
                "schema_rootpage": schema is not None and schema[0] == "sample" and schema[1] > 0,
                "explain_has_instructions": len(plan) > 0 and all(isinstance(row[1],str) for row in plan),
                "first_parameter_pair": first == [(1,"O'Brien")],
                "second_parameter_pair": second == [(2,"second")],
                "quoted_payload_not_sql": quoted == [],
                "integer_affinity_text": numeric_text == [(1,"O'Brien")],
                "negative_wrong_bind_rejected": wrong_bind == "ProgrammingError",
                "cursor_close_connection_reusable": reusable == 2,
                "persisted_and_integrity": persistent == [(1,"O'Brien"),(2,"second")] and integrity == "ok",
            }
            return {
                "lab":"L02", "status":"pass" if all(oracles.values()) else "fail",
                "environment":{"python":sys.version,"platform":platform.platform(),
                    "sqlite_version":con.execute("SELECT sqlite_version()").fetchone()[0],
                    "sqlite_source_id":con.execute("SELECT sqlite_source_id()").fetchone()[0],
                    "journal_mode":con.execute("PRAGMA journal_mode").fetchone()[0]},
                "fixture":{"rows":[[1,"O'Brien"],[2,"second"]],"sql":sql,
                    "binds":[[1,"O'Brien"],[2,"second"],[1,"O'Brien' OR 1=1 --"],["1","O'Brien"],[1]]},
                "events":events,
                "observed":{"rootpage":schema[1],"explain_instruction_count":len(plan),
                    "explain_first_opcodes":[row[1] for row in plan[:8]],
                    "first":first,"second":second,"quoted":quoted,
                    "numeric_text":numeric_text,"negative_exception":wrong_bind,
                    "reusable_count":reusable,"integrity_check":integrity},
                "oracles":oracles,
                "limitations":["EXPLAIN opcodes and positions are not a stable API.",
                    "Python cursor operations do not expose native prepare/step/finalize directly.",
                    "No B-tree/pager/VFS I/O trace or power-loss durability claim.",
                    "Only disposable fixture; external database paths not accepted."]}
        finally:
            con.close()

def main():
    if len(sys.argv) != 1:
        print("No arguments accepted", file=sys.stderr)
        return 2
    report = run()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
