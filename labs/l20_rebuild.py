"""L20/C18: transactional table rebuild, dependent objects and rollback.

Run: python3 labs/l20_rebuild.py
All failures are confined to disposable databases. No sleep or external services.
"""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def engine(db):
    return {"version": db.execute("select sqlite_version()").fetchone()[0],
            "source_id": db.execute("select sqlite_source_id()").fetchone()[0]}


def schema(db):
    return {row[0]: row[1] for row in db.execute(
        "select name, sql from sqlite_master where type in ('table','index','trigger') "
        "and name not like 'sqlite_%' order by name")}


def verify(db):
    require(db.execute("pragma integrity_check").fetchone()[0] == "ok", "integrity")
    require(db.execute("pragma foreign_key_check").fetchall() == [], "foreign keys")
    require(db.execute("pragma foreign_keys").fetchone()[0] == 1, "FK setting")
    require(db.execute("select count(*) from items").fetchone()[0] == 3, "row count")
    require(db.execute("select count(*) from child").fetchone()[0] == 1, "child count")


def setup(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma foreign_keys=ON")
    db.executescript("""
        create table items(id integer primary key, sku text not null unique, qty integer not null);
        create table child(id integer primary key, item_id integer not null references items(id));
        create index items_qty on items(qty);
        create table audit(item_id integer not null, old_qty integer not null);
        create trigger items_qty_audit after update of qty on items
        begin insert into audit values(old.id,old.qty); end;
        insert into items values(1,'A',10),(2,'B',20),(3,'C',30);
        insert into child values(1,1);
    """)
    verify(db)
    return db


def rebuild(db, fail=False, omit_index=False):
    # Legacy FK references retain the original table name; use a fresh replacement
    # and preserve the parent name. Foreign keys are checked before COMMIT.
    db.execute("begin immediate")
    db.execute("pragma defer_foreign_keys=ON")
    try:
        db.execute("create table items_new(id integer primary key, sku text not null unique, "
                   "qty integer not null check(qty >= 0), note text not null default '')")
        db.execute("insert into items_new(id,sku,qty) select id,sku,qty from items")
        if fail:
            raise RuntimeError("INJECTED_PRECOMMIT")
        db.execute("drop table items")
        db.execute("alter table items_new rename to items")
        db.execute("create trigger items_qty_audit after update of qty on items "
                   "begin insert into audit values(old.id,old.qty); end")
        if not omit_index:
            db.execute("create index items_qty on items(qty)")
        require(db.execute("pragma foreign_key_check").fetchall() == [], "FK after rebuild")
        db.execute("commit")
    except BaseException:
        if db.in_transaction:
            db.execute("rollback")
        raise


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l20-") as tmp:
        path = Path(tmp) / "lab.db"
        db = setup(path)
        try:
            before = schema(db)
            before_rows = db.execute("select * from items order by id").fetchall()
            try:
                rebuild(db, fail=True)
            except RuntimeError as exc:
                require(str(exc) == "INJECTED_PRECOMMIT", "wrong injected failure")
            else:
                raise RuntimeError("failure injection escaped")
            require(not db.in_transaction, "rollback left transaction open")
            require(schema(db) == before, "DDL rollback did not restore schema")
            require(db.execute("select * from items order by id").fetchall() == before_rows,
                    "rollback changed rows")
            verify(db)
            # An omitted dependent index must be caught by the migration gate.
            rebuild(db, omit_index=True)
            require("items_qty" not in schema(db), "negative index fixture invalid")
            try:
                require("items_qty" in schema(db), "MISSING_INDEX_DETECTED")
            except RuntimeError as exc:
                require(str(exc) == "MISSING_INDEX_DETECTED", "wrong negative failure")
            else:
                raise RuntimeError("missing index escaped")
            # Recreate the missing object before the positive acceptance gate.
            db.execute("create index items_qty on items(qty)")
            verify(db)
            require("items_qty_audit" in schema(db), "trigger missing")
            db.execute("update items set qty=11 where id=1")
            require(db.execute("select item_id,old_qty from audit").fetchall() == [(1,10)],
                    "trigger behavior")
            try:
                db.execute("update items set qty=-1 where id=1")
            except sqlite3.IntegrityError as exc:
                require(getattr(exc, "sqlite_errorcode", 0) & 255 == sqlite3.SQLITE_CONSTRAINT,
                        "wrong CHECK error")
            else:
                raise RuntimeError("CHECK negative escaped")
            require(db.execute("select qty from items where id=1").fetchone()[0] == 11,
                    "failed CHECK changed row")
            db.close()
            db = sqlite3.connect(path, isolation_level=None)
            db.execute("pragma foreign_keys=ON")
            verify(db)
            require("items_qty" in schema(db) and "items_qty_audit" in schema(db),
                    "dependent objects missing after reopen")
            print(json.dumps({
                "lab": "L20", "chapter": "C18", "sqlite": engine(db),
                "environment": {"python": platform.python_version(), "os": platform.platform(),
                                "database": "disposable TemporaryDirectory"},
                "inputs": {"items": 3, "children": 1, "fault": "before DROP/COMMIT"},
                "oracles": {"rollback_schema": True, "rollback_rows": True,
                            "missing_index_negative": True, "fk": True,
                            "trigger": True, "check_negative": True, "reopen": True},
                "limitations": "Single process; no concurrent writers, power failure or I/O injection."
            }, indent=2, sort_keys=True))
        finally:
            db.close()


if __name__ == "__main__":
    main()
