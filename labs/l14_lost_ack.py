#!/usr/bin/env python3
"""L14 / C12: committed receipt survives a lost response.

Only disposable SQLite files and child processes are used. The parent waits for
explicit protocol messages, never for an arbitrary sleep. SIGKILL is not used:
the worker exits after a committed ACK but before sending a business response.
This models response loss, not a crash or power-loss durability guarantee.
"""
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def identity(db):
    return {
        "version": db.execute("select sqlite_version()").fetchone()[0],
        "source_id": db.execute("select sqlite_source_id()").fetchone()[0],
    }


def transfer(db, key, amount):
    """Atomic receipt and movement; reject changed payloads."""
    require(isinstance(key, str) and bool(key.strip()), "INVALID_IDEMPOTENCY_KEY")
    db.execute("BEGIN IMMEDIATE")
    try:
        previous = db.execute("SELECT amount FROM receipts WHERE id=?", (key,)).fetchone()
        if previous is not None:
            require(previous[0] == amount, "IDEMPOTENCY_CONFLICT")
            db.execute("COMMIT")
            return "replayed"
        require(amount > 0, "INVALID_AMOUNT")
        balance = db.execute("SELECT qty FROM stock WHERE location='A'").fetchone()[0]
        require(balance >= amount, "INSUFFICIENT_STOCK")
        db.execute("UPDATE stock SET qty=qty-? WHERE location='A'", (amount,))
        db.execute("UPDATE stock SET qty=qty+? WHERE location='B'", (amount,))
        db.execute("INSERT INTO receipts(id,amount) VALUES (?,?)", (key, amount))
        db.execute("COMMIT")
        return "applied"
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def snapshot(db):
    return {
        "stock": db.execute("SELECT location,qty FROM stock ORDER BY location").fetchall(),
        "receipts": db.execute("SELECT id,amount FROM receipts ORDER BY id").fetchall(),
    }


def child(path, phase):
    db = sqlite3.connect(path, isolation_level=None, timeout=0)
    try:
        if phase == "before_commit":
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE stock SET qty=qty-3 WHERE location='A'")
            print("BEFORE_COMMIT_ACK", flush=True)
            # Simulate process termination before COMMIT. Connection close rolls back.
            return
        require(transfer(db, "op-1", 3) == "applied", "worker did not apply")
        print("COMMIT_ACK", flush=True)
        # Deliberately omit the business response.
    finally:
        db.close()


def worker(path, phase):
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(path), phase],
        text=True, capture_output=True, timeout=15, check=False,
    )
    require(process.returncode == 0, "worker failed: " + process.stderr)
    expected = "BEFORE_COMMIT_ACK" if phase == "before_commit" else "COMMIT_ACK"
    require(process.stdout.strip() == expected, "unexpected protocol: " + repr(process.stdout))
    return expected


def setup(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.executescript("""
        PRAGMA journal_mode=DELETE;
        CREATE TABLE stock(location TEXT PRIMARY KEY, qty INTEGER NOT NULL CHECK(qty>=0));
        CREATE TABLE receipts(id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(id))>0), amount INTEGER NOT NULL CHECK(amount>0));
        INSERT INTO stock VALUES ('A',10),('B',0);
    """)
    return db


def run():
    checks = {}
    events = []
    with tempfile.TemporaryDirectory(prefix="sqlite-l14-") as directory:
        path = Path(directory) / "commit.sqlite3"
        db = setup(path)
        engine = identity(db)
        db.close()
        events.append(worker(path, "committed"))
        db = sqlite3.connect(path, isolation_level=None)
        checks["committed_state"] = snapshot(db) == {
            "stock": [("A", 7), ("B", 3)], "receipts": [("op-1", 3)]}
        checks["replay_same_payload"] = transfer(db, "op-1", 3) == "replayed"
        checks["no_double_debit"] = snapshot(db)["stock"] == [("A", 7), ("B", 3)]
        try:
            transfer(db, "op-1", 4)
        except RuntimeError as error:
            checks["different_payload_rejected"] = str(error) == "IDEMPOTENCY_CONFLICT"
        else:
            checks["different_payload_rejected"] = False
        checks["unchanged_after_conflict"] = snapshot(db) == {
            "stock": [("A", 7), ("B", 3)], "receipts": [("op-1", 3)]}
        checks["integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        db.close()

        before = Path(directory) / "before.sqlite3"
        db = setup(before)
        db.close()
        events.append(worker(before, "before_commit"))
        db = sqlite3.connect(before, isolation_level=None)
        checks["uncommitted_rolled_back"] = snapshot(db) == {
            "stock": [("A", 10), ("B", 0)], "receipts": []}
        checks["retry_after_rollback"] = transfer(db, "op-1", 3) == "applied"
        checks["final_conservation"] = snapshot(db)["stock"] == [("A", 7), ("B", 3)]
        db.close()

    require(all(checks.values()), "L14 failed: " + repr(checks))
    print(json.dumps({"lab": "L14", "python": sys.version.split()[0],
                      "platform": platform.platform(), "sqlite": engine,
                      "events": events, "checks": checks,
                      "limits": "graceful worker exit models lost ACK; not SIGKILL, fsync or power loss"},
                     sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        child(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 1:
        run()
    else:
        raise SystemExit("usage: python labs/l14_lost_ack.py")
