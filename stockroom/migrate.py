"""CP08: stage canonical codes in restartable batches, then rebuild location atomically."""
from contextlib import closing
import hashlib
import json

from fixtures.f3_preflight import canonical

from tools.e1 import inspect_connection

from .environment import connect
from .ledger import require_version, write_transaction
from .operation import execute, parser
from .writer import watermark


def normalized(db):
    rows = db.execute("SELECT id,code FROM location ORDER BY id").fetchall()
    result, codes = [], set()
    for location_id, old in rows:
        new = canonical(old)
        if new is None:
            raise ValueError(f"invalid location code at {location_id}")
        if new in codes:
            raise ValueError(f"canonical location collision: {new}")
        codes.add(new)
        result.append((location_id, old, new))
    return result


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def rebuild(db):
    dependents = db.execute("""
        SELECT type,name,sql FROM sqlite_schema
        WHERE sql IS NOT NULL AND (type IN ('view','trigger')
                                   OR (type='index' AND tbl_name='location'))
        ORDER BY CASE type WHEN 'trigger' THEN 0 WHEN 'view' THEN 1 ELSE 2 END, name
    """).fetchall()
    for kind, name, _ in dependents:
        db.execute(f"DROP {kind.upper()} {quote(name)}")
    db.execute("""
        CREATE TABLE location_next (
          id ANY NOT NULL PRIMARY KEY CHECK (
            typeof(id)='text' AND instr(id,char(0))=0
            AND id GLOB '[A-Za-z0-9]*' AND id NOT GLOB '*[^A-Za-z0-9._-]*'
          ),
          code TEXT NOT NULL UNIQUE CHECK (
            length(code)>0 AND instr(code,char(0))=0 AND code NOT GLOB '*[^A-Z0-9-]*'
          ),
          code_history TEXT NOT NULL
        ) STRICT
    """)
    db.execute("INSERT INTO location_next SELECT id,canonical_code,old_code FROM location_stage")
    db.execute("DROP TABLE location")
    db.execute("ALTER TABLE location_next RENAME TO location")
    for kind, _, sql in reversed(dependents):
        db.execute(sql)
    for kind, name, _ in dependents:
        if kind == "view":
            db.execute(f"SELECT * FROM {quote(name)} LIMIT 0")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("foreign keys invalid after rebuild")
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("integrity check failed after rebuild")
    db.execute("DROP TABLE location_stage")
    db.execute("DROP TABLE location_migration")
    db.execute("PRAGMA user_version=2")


def step(path, batch_size=1, *, interrupt=None):
    if type(batch_size) is not int or not 1 <= batch_size <= 10_000:
        raise ValueError("batch size must be 1 to 10000")
    with closing(connect(path)) as db:
        # The rebuild briefly removes the parent table. Verify every FK before commit.
        db.execute("PRAGMA foreign_keys=OFF")
        with write_transaction(db):
            require_version(db, 1)
            before = watermark(db)
            rows = normalized(db)
            source_digest = fingerprint(rows)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS location_migration(
                  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                  digest TEXT NOT NULL, cursor INTEGER NOT NULL
                ) STRICT;
                CREATE TABLE IF NOT EXISTS location_stage(
                  id ANY NOT NULL PRIMARY KEY, old_code TEXT NOT NULL, canonical_code TEXT NOT NULL UNIQUE
                ) STRICT;
            """)
            db.execute("INSERT OR IGNORE INTO location_migration VALUES(1,?,0)", (source_digest,))
            digest, cursor = db.execute("SELECT digest,cursor FROM location_migration").fetchone()
            if digest != source_digest:
                raise ValueError("location input changed during migration")
            if not 0 <= cursor <= len(rows):
                raise ValueError("invalid migration cursor")
            if db.execute("SELECT id,old_code,canonical_code FROM location_stage ORDER BY id").fetchall() != rows[:cursor]:
                raise ValueError("staged location data or cursor invalid")
            if cursor < len(rows):
                batch = rows[cursor:cursor + batch_size]
                db.executemany("INSERT INTO location_stage VALUES(?,?,?)", batch)
                cursor += len(batch)
                db.execute("UPDATE location_migration SET cursor=? WHERE singleton=1", (cursor,))
                if interrupt:
                    interrupt("batch")
                return {"status": "staged", "cursor": cursor, "total": len(rows), "schema": 1}
            before_ledger = inspect_connection(db)
            if not before_ledger["ok"]:
                raise ValueError(f"source ledger fails O1: {before_ledger['errors']}")
            rebuild(db)
            locations = db.execute("SELECT id,code_history,code FROM location ORDER BY id").fetchall()
            if locations != rows:
                raise ValueError("rebuilt location codes differ from the staged mapping")
            if inspect_connection(db) != before_ledger:
                raise ValueError("rebuilt ledger differs from the validated source")
            if watermark(db) != before:
                raise ValueError("receipt boundary changed during rebuild")
            if interrupt:
                interrupt("rebuild")
        return {"status": "migrated", "cursor": cursor, "total": len(rows), "schema": 2}


def main():
    args = parser(__doc__)
    args.add_argument("--batch-size", type=int, default=1)
    options = args.parse_args()
    return execute(lambda: step(options.database, options.batch_size))


if __name__ == "__main__":
    raise SystemExit(main())
