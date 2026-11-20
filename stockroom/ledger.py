"""CP01: install schema v1 and load the shared F1 opening balances."""

from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3

from tools import e1

from .environment import connect, identity


SCHEMA_V1 = Path(__file__).with_name("schema_v1.sql")


@contextmanager
def write_transaction(db: sqlite3.Connection, trace=None):
    if db.in_transaction:
        raise ValueError("write_transaction requires an idle connection")
    phase = "begin"
    if trace:
        trace(phase)
    try:
        db.execute("BEGIN IMMEDIATE")
        phase = "work"
        if trace:
            trace(phase)
        yield
        phase = "commit"
        if trace:
            trace(phase)
        db.execute("COMMIT")
        if trace:
            trace("committed")
    except BaseException as error:
        if trace:
            trace(phase + "_failed", error)
        if db.in_transaction:
            db.execute("ROLLBACK")
            if trace:
                trace("rolled_back")
        raise


def require_version(db: sqlite3.Connection, version: int) -> dict:
    details = identity(db)
    if details["schema_version"] != version:
        raise ValueError(
            f"Expected Stockroom Ledger schema v{version}, found v{details['schema_version']}"
        )
    return details


def seed_f1(db: sqlite3.Connection) -> None:
    # Load the shared pilot in memory and copy just its stable opening data.
    # Application DDL and constraints come from schema_v1.sql.
    with closing(sqlite3.connect(":memory:", autocommit=True)) as fixture:
        fixture.executescript(e1.SCHEMA.read_text(encoding="utf-8"))
        db.executemany(
            "INSERT INTO item(id,sku) VALUES(?,?)",
            fixture.execute("SELECT id,sku FROM item ORDER BY id"),
        )
        db.executemany(
            "INSERT INTO location(id,code) VALUES(?,?)",
            fixture.execute("SELECT id,code FROM location ORDER BY id"),
        )
        db.executemany(
            "INSERT INTO opening_balance(item_id,location_id,quantity) VALUES(?,?,?)",
            fixture.execute("SELECT item_id,location_id,quantity FROM opening_balance ORDER BY item_id,location_id"),
        )
    db.execute(
        "INSERT INTO stock_balance(item_id,location_id,quantity) "
        "SELECT item_id,location_id,quantity FROM opening_balance"
    )


def initialize_ledger(path: Path) -> dict:
    with closing(connect(path)) as db:
        with write_transaction(db):
            require_version(db, 0)
            db.executescript(SCHEMA_V1.read_text(encoding="utf-8"))
            seed_f1(db)
            db.execute("PRAGMA user_version=1")
        return identity(db)


def check_ledger(path: Path) -> dict:
    with closing(connect(path, read_only=True)) as db:
        require_version(db, 1)
    return e1.inspect(path)
