#!/usr/bin/env python3
"""Disposable Linux E1 probes for process interruption and logical capacity."""

from contextlib import closing
import json
import multiprocessing
import signal
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.e1 import initialize, inspect

WATCHDOG = 10
BASELINE = (10, 2, 4, 8)
COMMITTED = (7, 5, 4, 8)


def connect(path, **kwargs):
    return sqlite3.connect(path, isolation_level=None, timeout=0, **kwargs)


def receive(pipe):
    if not pipe.poll(WATCHDOG):
        raise TimeoutError("worker missed its ACK deadline")
    return pipe.recv()


def transfer(connection, operation_id="tx-001", quantity=3):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "INSERT INTO transfer VALUES (?,'item-bolt','loc-north','loc-south',?)",
        (operation_id, quantity),
    )
    connection.executemany(
        "UPDATE stock_balance SET quantity=quantity+? WHERE item_id='item-bolt' AND location_id=?",
        [(-quantity, "loc-north"), (quantity, "loc-south")],
    )
    connection.executemany(
        "INSERT INTO journal_entry(transfer_id,item_id,location_id,delta)"
        " VALUES (?,'item-bolt',?,?)",
        [(operation_id, "loc-north", -quantity), (operation_id, "loc-south", quantity)],
    )


def worker(path, pipe):
    with pipe, closing(connect(path)) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        transfer(db)
        pipe.send(("STATEMENTS_DONE", db.in_transaction, db.execute("PRAGMA synchronous").fetchone()[0]))
        if receive(pipe) != "COMMIT":
            raise RuntimeError("unexpected supervisor command")
        db.execute("COMMIT")
        pipe.send(("COMMIT_RETURNED", db.in_transaction))
        if receive(pipe) != "RELEASE":
            raise RuntimeError("unexpected supervisor command")


def interruption_case(path, mode, cut):
    initialize(path)
    with closing(connect(path)) as setup:
        effective_mode = setup.execute(f"PRAGMA journal_mode={mode}").fetchone()[0]
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=worker, args=(path, child))
    process.start()
    child.close()
    transcript = []
    with parent:
        try:
            transcript.append(receive(parent))
            if cut != "before_commit":
                parent.send("COMMIT")
                transcript.append(receive(parent))
            if cut == "normal":
                parent.send("RELEASE")
            else:
                process.kill()
            process.join(WATCHDOG)
            if process.is_alive():
                raise TimeoutError("worker failed to exit")
            exitcode = process.exitcode
        finally:
            if process.is_alive():
                process.kill()
                process.join(WATCHDOG)
            process.close()
    files = {entry.name: entry.stat().st_size for entry in path.parent.iterdir()}
    # O1 opens read-only. Let SQLite recover via a writable connection first.
    with closing(connect(path)) as reopened:
        reopened_items = reopened.execute("SELECT count(*) FROM transfer").fetchone()[0]
    oracle = inspect(path)
    expected = BASELINE if cut == "before_commit" else COMMITTED
    committed = cut != "before_commit"
    return {
        "input": {"journal_mode": mode, "cut": cut},
        "journal_mode": effective_mode,
        "acks": transcript,
        "worker_exit": exitcode,
        "before_reopen_bytes": files,
        "reopened_transfer_count": reopened_items,
        "o1": oracle,
        "checks": {
            "mode": effective_mode == mode.lower(),
            "ack_boundary": transcript == (
                [("STATEMENTS_DONE", True, 2), ("COMMIT_RETURNED", False)]
                if committed else [("STATEMENTS_DONE", True, 2)]
            ),
            "exit": exitcode == (0 if cut == "normal" else -signal.SIGKILL),
            "reopen": reopened_items == int(committed),
            "o1": oracle["ok"],
            "ledger": tuple(row["quantity"] for row in oracle["balances"]) == expected
            and oracle["transfers"] == int(committed)
            and oracle["journal_entries"] == 2 * int(committed),
        },
    }


def capture_insert(db, key, size):
    try:
        db.execute("INSERT INTO capacity VALUES (?,zeroblob(?))", (key, size))
    except sqlite3.Error as error:
        return {"name": error.sqlite_errorname, "code": error.sqlite_errorcode,
                "message": str(error), "in_transaction": db.in_transaction}
    return {"name": None, "in_transaction": db.in_transaction}


def capacity_case(path, capped):
    payload = 64 * 1024
    with closing(connect(path)) as db:
        db.execute("PRAGMA page_size=1024")
        db.execute("CREATE TABLE capacity(id INTEGER PRIMARY KEY, payload BLOB)")
        capture_insert(db, 1, 32)
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        before = db.execute("PRAGMA page_count").fetchone()[0]
        requested = before + 4 if capped else before + 128
        applied = db.execute(f"PRAGMA max_page_count={requested}").fetchone()[0]
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO capacity VALUES (2,zeroblob(32))")
        outcome = capture_insert(db, 3, payload)
        if db.in_transaction:
            db.execute("COMMIT" if outcome["name"] is None else "ROLLBACK")
        pages = db.execute("PRAGMA page_count").fetchone()[0]
    with closing(connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT id,length(payload) FROM capacity ORDER BY id").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        readonly = capture_insert(db, 4, 32)
        persisted = db.execute("SELECT count(*) FROM capacity").fetchone()[0]
    return {
        "input": {"capped": capped, "payload_bytes": payload},
        "page_size": page_size,
        "page_count_before": before,
        "requested_page_limit": requested,
        "effective_page_limit": applied,
        "page_count_after": pages,
        "file_bytes": path.stat().st_size,
        "write": outcome,
        "readonly_write": readonly,
        "reopen_rows": rows,
        "integrity": integrity,
        "checks": {
            "limit": applied == requested and pages <= applied and path.stat().st_size == pages * page_size,
            "classified_capacity": outcome["name"] == ("SQLITE_FULL" if capped else None),
            "classified_readonly": readonly["name"] == "SQLITE_READONLY" and persisted == len(rows),
            "reopen": rows == ([(1, 32)] if capped else [(1, 32), (2, 32), (3, payload)]),
            "integrity": integrity == [("ok",)],
        },
    }


def main():
    with TemporaryDirectory(prefix="sqlite-work-e1-faults-") as tmp:
        root = Path(tmp)
        interruptions = []
        for mode in ("DELETE", "WAL"):
            for cut in ("before_commit", "after_commit", "normal"):
                trial = root / f"{mode.lower()}-{cut}"
                trial.mkdir()
                interruptions.append(interruption_case(trial / "ledger.db", mode, cut))
        limits = [capacity_case(root / f"capacity-{capped}.db", capped) for capped in (True, False)]
        with closing(connect(":memory:")) as db:
            source_id = db.execute("SELECT sqlite_source_id()").fetchone()[0]
    checks = {"L22": all(all(case["checks"].values()) for case in interruptions),
              "L23_portable_subset": all(all(case["checks"].values()) for case in limits)}
    print(json.dumps({"sqlite_version": sqlite3.sqlite_version, "sqlite_source_id": source_id,
                      "python": sys.version, "oracles": checks, "L22": interruptions,
                      "L23": limits}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
