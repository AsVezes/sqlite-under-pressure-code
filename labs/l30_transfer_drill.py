#!/usr/bin/env python3
"""L30/C28: isolated failover drill, NOT the full CP11/Stockroom replay.

Simulates loss of an active workspace after a verified online backup. All
databases are disposable. RPO is counted in committed operations; elapsed
time is a local observation, not an availability guarantee.
"""
from contextlib import closing
import hashlib
import json
import os
import platform
import sqlite3
import tempfile
import time
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path, expected):
    with closing(sqlite3.connect(path)) as db:
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                "structural integrity failed")
        require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                "foreign key violation")
        rows = db.execute("SELECT op_id, delta FROM receipts ORDER BY op_id").fetchall()
        require(rows == expected, "receipt continuity mismatch")
        require(db.execute("SELECT amount FROM balance").fetchone()[0] ==
                sum(v for _, v in expected), "balance invariant failed")
        return rows


def apply_receipt(db, op_id, delta):
    """One atomic receipt decision; a reused ID must match its stored payload."""
    require(type(op_id) is int and op_id > 0, "invalid receipt operation ID")
    require(type(delta) is int and delta > 0, "invalid receipt delta")
    stored = db.execute("SELECT delta FROM receipts WHERE op_id=?", (op_id,)).fetchone()
    if stored is not None:
        if stored[0] != delta:
            raise ValueError("operation ID already committed with a different payload")
        return False
    db.execute("INSERT INTO receipts(op_id,delta) VALUES(?,?)", (op_id, delta))
    updated = db.execute("UPDATE balance SET amount=amount+?", (delta,)).rowcount
    require(updated == 1, "balance row not updated exactly once")
    return True


def submit_receipt(db, op_id, delta):
    """Keep lookup, insertion and balance effects inside one write transaction."""
    db.execute("BEGIN IMMEDIATE")
    try:
        applied = apply_receipt(db, op_id, delta)
        db.commit()
        return applied
    except BaseException:
        db.rollback()
        raise


def reject_conflicting_receipt(db, path, expected, op_id, delta):
    """Exercise the real replay path and reject a different payload causally."""
    try:
        submit_receipt(db, op_id, delta)
    except ValueError as exc:
        require(str(exc) == "operation ID already committed with a different payload",
                "negative control: conflict failed for the wrong reason")
    else:
        raise RuntimeError("negative control: conflicting receipt accepted")
    require(check(path, expected) == expected,
            "negative control: conflict changed the recovered database")
    return True


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l30-") as root:
        folder = Path(root)
        active = folder / "active.sqlite"
        backup = folder / "verified.sqlite"
        recovered = folder / "recovered.sqlite"
        with closing(sqlite3.connect(active)) as db:
            engine = {"version": db.execute("SELECT sqlite_version()").fetchone()[0],
                      "source_id": db.execute("SELECT sqlite_source_id()").fetchone()[0]}
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("CREATE TABLE receipts(op_id INTEGER PRIMARY KEY, delta INTEGER NOT NULL);"
                             "CREATE TABLE balance(amount INTEGER NOT NULL);"
                             "INSERT INTO balance VALUES(0);")
            for op in range(1, 6):
                require(submit_receipt(db, op, 1),
                        "initial receipt unexpectedly treated as a replay")
            expected_backup = [(i, 1) for i in range(1, 6)]
            check(active, expected_backup)
            with closing(sqlite3.connect(backup)) as target:
                db.backup(target)
            require(check(backup, expected_backup) == expected_backup, "backup gate failed")
            backup_sha = digest(backup)
            # Commit acknowledged AFTER the backup cut; this operation is at risk.
            require(submit_receipt(db, 6, 1),
                    "post-backup receipt unexpectedly treated as a replay")
            require(check(active, expected_backup + [(6, 1)])[-1] == (6, 1),
                    "post-backup commit missing")
        start = time.perf_counter_ns()
        # Logical loss: active is excluded from recovery. Never damage a real file.
        recovered.write_bytes(backup.read_bytes())
        require(digest(recovered) == backup_sha, "restore digest mismatch")
        require(check(recovered, expected_backup) == expected_backup, "restore gate failed")
        # Negative: the restore MUST NOT be reported as zero-loss.
        lost = 6 - len(check(recovered, expected_backup))
        require(lost == 1, "negative control: expected one acknowledged operation absent")
        with closing(sqlite3.connect(recovered)) as db:
            # An identical retry traverses the same transaction path and writes nothing.
            require(submit_receipt(db, 5, 1) is False,
                    "identical receipt was applied twice")
            require(check(recovered, expected_backup) == expected_backup,
                    "identical retry changed the recovered database")
            # A local comparison, or INSERT OR IGNORE, is not a negative-control test.
            conflict_rejected = reject_conflicting_receipt(
                db, recovered, expected_backup, 5, 2
            )
            require(submit_receipt(db, 6, 1),
                    "reconciliation receipt unexpectedly treated as a replay")
        require(check(recovered, expected_backup + [(6, 1)])[-1] == (6, 1),
                "reconciliation failed")
        restore_ms = (time.perf_counter_ns() - start) / 1_000_000
        print(json.dumps({"lab": "L30", "chapter": "C28", "engine": engine,
                          "environment": {"python": platform.python_version(),
                                          "os": platform.platform(), "cwd": os.getcwd()},
                          "backup_sha256": backup_sha, "backup_cut": 5,
                          "last_acknowledged": 6, "rpo_operations_observed": lost,
                          "restore_and_reconcile_ms_observed": round(restore_ms, 3),
                          "negative_zero_loss_claim_rejected": True,
                          "negative_conflicting_receipt_rejected": conflict_rejected,
                          "final_receipts": 6, "oracle": "PASS",
                          "limitations": "Synthetic one-process transfer drill only; no CP11, "
                          "external effects, multi-host failover, real crash or power loss. "
                          "Time is not production RTO; 60s/120s targets not certified."},
                         sort_keys=True))


if __name__ == "__main__":
    main()
