"""CP02: hold one write transaction for a transfer and both journal legs."""

from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sqlite3

from .environment import connect
from .ledger import require_ledger, write_transaction


MAX_TRANSFER = 1_000_000_000
MAX_BALANCE = (1 << 63) - 1
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class Transfer:
    id: str
    item_id: str
    source_location_id: str
    destination_location_id: str
    quantity: int

    def __post_init__(self):
        for name in ("id", "item_id", "source_location_id", "destination_location_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"Invalid {name}: expected a canonical identifier")
        if self.source_location_id == self.destination_location_id:
            raise ValueError("The source and destination must differ")
        if type(self.quantity) is not int or not 1 <= self.quantity <= MAX_TRANSFER:
            raise ValueError(f"Quantity must be an integer from 1 to {MAX_TRANSFER}")


def apply_in_transaction(
    db: sqlite3.Connection, request: Transfer, *, fail_after_debit: bool = False
) -> None:
    """Apply one transfer within a caller-owned write transaction using a savepoint."""
    if not db.in_transaction or db.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise ValueError("Transfer requires an active transaction with foreign keys enabled")
    require_ledger(db)
    db.execute("SAVEPOINT stockroom_transfer")
    try:
        db.execute(
            "INSERT INTO transfer(id,item_id,source_location_id,destination_location_id,quantity) "
            "VALUES(?,?,?,?,?)",
            (request.id, request.item_id, request.source_location_id,
             request.destination_location_id, request.quantity),
        )
        source = db.execute(
            "UPDATE stock_balance SET quantity=quantity-? "
            "WHERE item_id=? AND location_id=? AND quantity>=?",
            (request.quantity, request.item_id, request.source_location_id, request.quantity),
        )
        if source.rowcount != 1:
            raise ValueError("Insufficient stock or missing source balance")
        if fail_after_debit:
            raise RuntimeError("Deliberate failure after debit")
        destination = db.execute(
            "UPDATE stock_balance SET quantity=quantity+? "
            "WHERE item_id=? AND location_id=? AND quantity<=?",
            (request.quantity, request.item_id, request.destination_location_id,
             MAX_BALANCE - request.quantity),
        )
        if destination.rowcount != 1:
            raise ValueError("Destination balance would overflow or is missing")
        db.executemany(
            "INSERT INTO journal_entry(transfer_id,item_id,location_id,delta) VALUES(?,?,?,?)",
            [
                (request.id, request.item_id, request.source_location_id, -request.quantity),
                (request.id, request.item_id, request.destination_location_id, request.quantity),
            ],
        )
        db.execute("RELEASE stockroom_transfer")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK TO stockroom_transfer")
            db.execute("RELEASE stockroom_transfer")
        raise


def transfer(path: Path, request: Transfer, *, fail_after_debit: bool = False) -> dict:
    with closing(connect(path)) as db:
        with write_transaction(db):
            apply_in_transaction(db, request, fail_after_debit=fail_after_debit)
    return {"status": "committed", "transfer": asdict(request)}
