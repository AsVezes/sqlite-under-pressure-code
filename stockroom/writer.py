"""CP05: retry a complete transfer with a stable request and durable receipt."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from time import monotonic, sleep

from .environment import connect
from .ledger import require_version, write_transaction
from .observe import event
from .operation import execute, parser
from .transfer import Transfer, apply_in_transaction


def install(path):
    with closing(connect(path)) as db, write_transaction(db):
        require_version(db, 1)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS receipt(
              seq INTEGER PRIMARY KEY, transfer_id ANY NOT NULL UNIQUE REFERENCES transfer(id)
            ) STRICT;
            INSERT INTO receipt(transfer_id)
              SELECT id FROM transfer WHERE id NOT IN (SELECT transfer_id FROM receipt) ORDER BY rowid;
            CREATE TRIGGER IF NOT EXISTS record_transfer_receipt AFTER INSERT ON transfer
            BEGIN INSERT INTO receipt(transfer_id) VALUES (new.id); END;
        """)
        return {"receipt_count": watermark(db)}


def watermark(db):
    count, maximum = db.execute("SELECT count(*),coalesce(max(seq),0) FROM receipt").fetchone()
    transfers = db.execute("SELECT count(*) FROM transfer").fetchone()[0]
    minimum = db.execute("SELECT coalesce(min(seq),1) FROM receipt").fetchone()[0]
    if count != maximum or transfers != count or minimum != 1:
        raise ValueError("receipt sequence or transfer count inconsistent")
    return maximum


def submit(path, request, wait_ms=500):
    if type(wait_ms) is not int or not 0 <= wait_ms <= 60_000:
        raise ValueError("wait-ms must be an integer from 0 to 60000")
    deadline = monotonic() + wait_ms / 1000
    events = []
    while True:
        try:
            with closing(connect(path, timeout=0)) as db:
                with write_transaction(db, lambda phase, error=None: event(events, phase, error)):
                    require_version(db, 1)
                    prior = db.execute(
                        "SELECT t.item_id,t.source_location_id,t.destination_location_id,t.quantity,r.seq "
                        "FROM transfer t JOIN receipt r ON r.transfer_id=t.id WHERE t.id=?", (request.id,)
                    ).fetchone()
                    if prior:
                        if prior[:4] != (request.item_id, request.source_location_id,
                                         request.destination_location_id, request.quantity):
                            raise ValueError("operation ID already committed with a different payload")
                        sequence = prior[4]
                    else:
                        apply_in_transaction(db, request)
                        sequence = db.execute("SELECT seq FROM receipt WHERE transfer_id=?",
                                              (request.id,)).fetchone()[0]
            return {"id": request.id, "receipt": sequence, "replayed": prior is not None,
                    "events": events}
        except sqlite3.OperationalError as exc:
            remaining = deadline - monotonic()
            code = getattr(exc, "sqlite_errorcode", 0)
            if remaining <= 0 or code & 255 != sqlite3.SQLITE_BUSY or code == sqlite3.SQLITE_BUSY_SNAPSHOT:
                exc.events = events
                raise
            event(events, "retry", exc)
            sleep(min(0.01, remaining))
            if monotonic() >= deadline:
                exc.events = events
                raise
        except (ValueError, sqlite3.Error) as exc:
            exc.events = events
            raise


def run_queue(path, requests, wait_ms=500):
    return [submit(path, request, wait_ms) for request in requests]


def main():
    args = parser(__doc__)
    sub = args.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    send = sub.add_parser("submit")
    for name in ("id", "item_id", "source_location_id", "destination_location_id"):
        send.add_argument(name)
    send.add_argument("quantity", type=int)
    send.add_argument("--wait-ms", type=int, default=500)
    batch = sub.add_parser("queue")
    batch.add_argument("requests", type=Path)
    batch.add_argument("--wait-ms", type=int, default=500)
    options = args.parse_args()

    def command():
        if options.command == "install":
            return install(options.database)
        if options.command == "submit":
            request = Transfer(options.id, options.item_id, options.source_location_id,
                               options.destination_location_id, options.quantity)
            return submit(options.database, request, options.wait_ms)
        rows = json.loads(options.requests.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("queue input must be a JSON list of transfer objects")
        try:
            requests = [Transfer(**row) for row in rows]
        except TypeError as exc:
            raise ValueError("invalid queue transfer object") from exc
        return run_queue(options.database, requests, options.wait_ms)

    return execute(command)


if __name__ == "__main__":
    raise SystemExit(main())
