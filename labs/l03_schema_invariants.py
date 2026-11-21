"""L03 — isolated schema invariants and per-connection foreign-key controls."""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l03-") as root:
        db = Path(root) / "schema.sqlite3"
        with sqlite3.connect(db, isolation_level=None) as a, sqlite3.connect(db, isolation_level=None) as b:
            version, source_id = a.execute("SELECT sqlite_version(), sqlite_source_id()").fetchone()
            a.execute("PRAGMA foreign_keys=ON")
            b.execute("PRAGMA foreign_keys=OFF")
            require(a.execute("PRAGMA foreign_keys").fetchone()[0] == 1, "FK ON not applied")
            require(b.execute("PRAGMA foreign_keys").fetchone()[0] == 0, "FK OFF not applied")
            a.executescript("""
                CREATE TABLE parent(id TEXT PRIMARY KEY) STRICT;
                CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES parent(id));
                CREATE TABLE common_qty(q INTEGER CHECK(q >= 0));
                CREATE TABLE strict_qty(q INTEGER NOT NULL CHECK(q >= 0)) STRICT;
                INSERT INTO parent VALUES ('001');
            """)
            a.execute("INSERT INTO common_qty VALUES (?)", ("7",))
            common = a.execute("SELECT q, typeof(q) FROM common_qty").fetchone()
            a.execute("INSERT INTO strict_qty VALUES (?)", ("7",))
            strict = a.execute("SELECT q, typeof(q) FROM strict_qty").fetchone()
            a.execute("INSERT INTO common_qty VALUES (NULL)")
            outcomes = {}
            for name, sql, args in [
                ("strict_text", "INSERT INTO strict_qty VALUES (?)", ("not-an-integer",)),
                ("strict_null", "INSERT INTO strict_qty VALUES (NULL)", ()),
                ("strict_negative", "INSERT INTO strict_qty VALUES (-1)", ()),
                ("missing_parent", "INSERT INTO child(parent_id) VALUES ('absent')", ()),
                ("duplicate_parent", "INSERT INTO parent VALUES ('001')", ()),
            ]:
                try:
                    a.execute(sql, args)
                except sqlite3.Error as exc:
                    outcomes[name] = {"rejected": True, "code": getattr(exc, "sqlite_errorcode", None),
                                      "name": getattr(exc, "sqlite_errorname", None)}
                else:
                    outcomes[name] = {"rejected": False}
            b.execute("INSERT INTO child(parent_id) VALUES ('orphan')")
            violations = a.execute("PRAGMA foreign_key_check").fetchall()
            negative_detected = len(violations) == 1 and violations[0][0] == "child"
            b.execute("DELETE FROM child WHERE parent_id='orphan'")
            a.execute("INSERT INTO child(parent_id) VALUES ('001')")
            oracles = {
                "affinity_numeric_text": common == (7, "integer") and strict == (7, "integer"),
                "check_null_three_valued": a.execute("SELECT count(*) FROM common_qty WHERE q IS NULL").fetchone()[0] == 1,
                "invalid_inputs_rejected": all(x["rejected"] for x in outcomes.values()),
                "per_connection_fk_switch": negative_detected,
                "negative_control_detected": negative_detected,
                "fk_restored": a.execute("PRAGMA foreign_key_check").fetchall() == [],
                "leading_zero_parent_preserved": a.execute("SELECT parent_id FROM child").fetchone()[0] == "001",
            }
            evidence = {"lab": "L03", "python": sys.version.split()[0], "platform": platform.platform(),
                        "sqlite_version": version, "sqlite_source_id": source_id,
                        "database": "exclusive TemporaryDirectory (removed)",
                        "inputs": {"numeric_text": "7", "text_id": "001", "invalid_cases": list(outcomes)},
                        "rejections": outcomes, "negative_fk_rows": violations, "oracles": oracles,
                        "limitations": "Python SQLite binding only; no CLI; disposable orphan; no durability or concurrency claims"}
            require(all(oracles.values()), "L03 oracle failure: " + json.dumps(oracles))
            return evidence


if __name__ == "__main__":
    try:
        print(json.dumps({"status": "pass", **run()}, sort_keys=True, default=list))
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}), file=sys.stderr)
        sys.exit(1)
