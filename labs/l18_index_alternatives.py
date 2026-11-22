#!/usr/bin/env python3
"""L18/C16: disposable index alternatives; correctness before planner claims."""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def plan(db, sql, params=()):
    return [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql, params)]


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l18-") as scratch:
        path = Path(scratch) / "experiment.sqlite"
        with sqlite3.connect(path) as db:
            version, source_id = db.execute(
                "SELECT sqlite_version(), sqlite_source_id()"
            ).fetchone()
            db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, item INTEGER NOT NULL, "
                       "region TEXT NOT NULL, qty INTEGER NOT NULL)")
            db.executemany(
                "INSERT INTO events(id,item,region,qty) VALUES(?,?,?,?)",
                ((i, i % 31, ("north", "south", "west")[i % 3], i % 17)
                 for i in range(1, 12001)),
            )
            sql = ("SELECT id, qty FROM events WHERE item=? AND region=? "
                   "ORDER BY id")
            args = (17, "north")
            baseline = db.execute(sql, args).fetchall()
            require(bool(baseline), "positive fixture unexpectedly empty")
            before = plan(db, sql, args)
            db.execute("CREATE INDEX idx_item_region ON events(item, region)")
            db.execute("ANALYZE")
            compound = plan(db, sql, args)
            require(db.execute(sql, args).fetchall() == baseline,
                    "compound index changed query result")
            db.execute("DROP INDEX idx_item_region")
            db.execute("CREATE INDEX idx_region_item ON events(region, item)")
            db.execute("ANALYZE")
            reverse = plan(db, sql, args)
            require(db.execute(sql, args).fetchall() == baseline,
                    "reverse index changed query result")
            db.execute("DROP INDEX idx_region_item")
            db.execute("CREATE INDEX idx_cover ON events(item, region, qty)")
            db.execute("ANALYZE")
            covering = plan(db, sql, args)
            require(db.execute(sql, args).fetchall() == baseline,
                    "covering index changed query result")
            db.execute("CREATE INDEX idx_partial ON events(item) WHERE region='north'")
            partial_compatible = plan(
                db, "SELECT id FROM events WHERE item=? AND region='north'", (17,)
            )
            partial_incompatible = plan(
                db, "SELECT id FROM events WHERE item=? AND region='south'", (17,)
            )
            db.execute("CREATE INDEX idx_expression ON events((qty + 1))")
            expression = plan(db, "SELECT id FROM events WHERE qty + 1 = ?", (7,))
            negative = db.execute(sql, (18, "north")).fetchall()
            require(negative != baseline, "negative parameter substitution undetected")
            require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                    "integrity check failed")
            require(len(baseline) == len({row[0] for row in baseline}),
                    "duplicate primary keys in result")
            print(json.dumps({
                "lab": "L18", "chapter": "C16", "python": sys.version.split()[0],
                "platform": platform.platform(), "sqlite_version": version,
                "sqlite_source_id": source_id, "fixture": "temporary sqlite file",
                "rows": 12000, "parameters": list(args),
                "result_count": len(baseline), "negative_detected": True,
                "integrity_check": "ok",
                "plans": {"none": before, "compound": compound,
                          "reversed": reverse, "covering": covering,
                          "partial_compatible": partial_compatible,
                          "partial_incompatible": partial_incompatible,
                          "expression": expression},
                "limitations": [
                    "EQP wording and index selection are version/statistics dependent",
                    "No timing or write-amplification comparison; not full L18 acceptance",
                    "Partial index eligibility not asserted from unstable EQP strings",
                    "Filesystem type not measured"
                ],
            }, indent=2))


if __name__ == "__main__":
    run()
