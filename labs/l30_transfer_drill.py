#!/usr/bin/env python3
"""L30/C28: isolated failover drill, NOT the full CP11/Stockroom replay.

Simulates loss of an active workspace after a verified online backup. All
databases are disposable. RPO is counted in committed operations; elapsed
time is a local observation, not an availability guarantee.
"""
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
    with sqlite3.connect(path) as db:
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                "structural integrity failed")
        require(db.execute("PRAGMA foreign_key_check").fetchall() == [],
                "foreign key violation")
        rows = db.execute("SELECT op_id, delta FROM receipts ORDER BY op_id").fetchall()
        require(rows == expected, "receipt continuity mismatch")
        require(db.execute("SELECT amount FROM balance").fetchone()[0] ==
                sum(v for _, v in expected), "balance invariant failed")
        return rows


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l30-") as root:
        folder = Path(root)
        active = folder / "active.sqlite"
        backup = folder / "verified.sqlite"
        recovered = folder / "recovered.sqlite"
        with sqlite3.connect(active) as db:
            engine = {"version": db.execute("SELECT sqlite_version()").fetchone()[0],
                      "source_id": db.execute("SELECT sqlite_source_id()").fetchone()[0]}
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("CREATE TABLE receipts(op_id INTEGER PRIMARY KEY, delta INTEGER NOT NULL);"
                             "CREATE TABLE balance(amount INTEGER NOT NULL);"
                             "INSERT INTO balance VALUES(0);")
            for op in range(1, 6):
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO receipts VALUES(?,?)", (op, 1))
                db.execute("UPDATE balance SET amount=amount+1")
                db.commit()
            expected_backup = [(i, 1) for i in range(1, 6)]
            check(active, expected_backup)
            with sqlite3.connect(backup) as target:
                db.backup(target)
            require(check(backup, expected_backup) == expected_backup, "backup gate failed")
            backup_sha = digest(backup)
            # Commit acknowledged AFTER the backup cut; this operation is at risk.
            db.execute("INSERT INTO receipts VALUES(6,1)")
            db.execute("UPDATE balance SET amount=amount+1")
            db.commit()
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
        with sqlite3.connect(recovered) as db:
            # Replaying a known receipt is idempotent, even after ambiguous acknowledgement.
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO receipts VALUES(5,1)")
            require(db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 5,
                    "duplicate receipt created")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO receipts VALUES(6,1)")
            db.execute("UPDATE balance SET amount=amount+1")
            db.commit()
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
                          "final_receipts": 6, "oracle": "PASS",
                          "limitations": "Synthetic one-process transfer drill only; no CP11, "
                          "external effects, multi-host failover, real crash or power loss. "
                          "Time is not production RTO; 60s/120s targets not certified."},
                         sort_keys=True))


if __name__ == "__main__":
    main()
