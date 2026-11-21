"""L04: disposable rowid versus WITHOUT ROWID page-layout probe (C04).

Run: python3 labs/l04_pages.py
No external database paths, network access, or destructive faults.
"""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l04-") as tmp:
        root = Path(tmp)
        outcomes = {}
        for kind, suffix in (("rowid", ""), ("without_rowid", " WITHOUT ROWID")):
            path = root / (kind + ".sqlite3")
            db = sqlite3.connect(path)
            try:
                db.execute("PRAGMA page_size=4096")
                db.execute("PRAGMA auto_vacuum=NONE")
                db.execute("CREATE TABLE records (item TEXT NOT NULL, location TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(item, location))" + suffix)
                db.execute("CREATE INDEX records_location ON records(location)")
                rows = [(f"item-{i:04d}", f"loc-{i % 7}", "X" * (50 + i % 13)) for i in range(300)]
                db.executemany("INSERT INTO records VALUES (?, ?, ?)", rows)
                db.commit()
                before = db.execute("SELECT item, location, payload FROM records ORDER BY item, location").fetchall()
                pages_before = db.execute("PRAGMA page_count").fetchone()[0]
                bytes_before = path.stat().st_size
                db.execute("DELETE FROM records WHERE item < ?", ("item-0100",))
                db.commit()
                after = db.execute("SELECT item, location, payload FROM records ORDER BY item, location").fetchall()
                pages_after = db.execute("PRAGMA page_count").fetchone()[0]
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
                try:
                    dbstat = db.execute("SELECT name, count(*) FROM dbstat GROUP BY name ORDER BY name").fetchall()
                    dbstat_available = True
                except sqlite3.OperationalError as exc:
                    if "no such table: dbstat" not in str(exc).lower():
                        raise
                    dbstat, dbstat_available = [], False
                outcomes[kind] = {
                    "rows_before": before, "rows_after": after,
                    "page_size": db.execute("PRAGMA page_size").fetchone()[0],
                    "auto_vacuum": db.execute("PRAGMA auto_vacuum").fetchone()[0],
                    "pages_before": pages_before, "pages_after": pages_after,
                    "freelist_after": db.execute("PRAGMA freelist_count").fetchone()[0],
                    "bytes_before": bytes_before, "bytes_after": path.stat().st_size,
                    "integrity": integrity, "dbstat_available": dbstat_available,
                    "dbstat_pages": dbstat,
                    "rootpages": db.execute("SELECT name, rootpage FROM sqlite_schema WHERE rootpage > 0 ORDER BY name").fetchall(),
                }
            finally:
                db.close()
        a, b = outcomes["rowid"], outcomes["without_rowid"]
        checks = {
            "same_initial_rows": a["rows_before"] == b["rows_before"] and len(a["rows_before"]) == 300,
            "same_remaining_rows": a["rows_after"] == b["rows_after"] and len(a["rows_after"]) == 200,
            "integrity_both": a["integrity"] == b["integrity"] == "ok",
            "fixed_page_size": a["page_size"] == b["page_size"] == 4096,
            "auto_vacuum_disabled": a["auto_vacuum"] == b["auto_vacuum"] == 0,
            "delete_not_automatic_vacuum": all(x["bytes_after"] == x["bytes_before"] for x in (a, b)),
            "schema_rootpages_present": all(len(x["rootpages"]) >= 2 for x in (a, b)),
        }
        # Negative control: structural integrity cannot detect a business-level
        # missing row; deliberately compare the deleted state to the original.
        negative_control_detected = a["rows_before"] != a["rows_after"] and a["integrity"] == "ok"
        checks["negative_control_detected"] = negative_control_detected
        # Never claim a particular layout is always smaller or faster.
        report = {
            "lab": "L04", "status": "pass" if all(checks.values()) else "fail",
            "environment": {"python": platform.python_version(), "os": platform.platform(),
                            "sqlite_version": sqlite3.sqlite_version,
                            "sqlite_source_id": sqlite3.connect(":memory:").execute("SELECT sqlite_source_id()").fetchone()[0]},
            "checks": checks,
            "measurements": {kind: {k: v for k, v in x.items() if k not in ("rows_before", "rows_after")}
                             for kind, x in outcomes.items()},
            "limitations": ["single local Python-linked SQLite build", "no fixed winner for physical footprint",
                            "dbstat optional", "no durability, performance, or cross-platform claim"],
        }
        return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["status"] == "pass" else 1)
